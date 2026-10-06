#!/usr/bin/env python3
"""Upload ciphertext and restore tools; read token only through getpass or env."""
import base64
import getpass
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = 'xuzinann/VM-backup'
TAG = 'vm-backup-20261005'
BASE = Path(__file__).resolve().parent
ASSETS = BASE / 'assets'


def api(token, path, method='GET', data=None):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request('https://api.github.com' + path, data=body, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'VM-backup-migration',
                 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=60) as response:
        result = response.read()
    return json.loads(result) if result else None


def upload(token, release_id, path):
    connection = http.client.HTTPSConnection('uploads.github.com', timeout=600,
                                             context=ssl.create_default_context())
    try:
        url = f'/repos/{REPO}/releases/{release_id}/assets?name=' + urllib.parse.quote(path.name)
        connection.putrequest('POST', url)
        for key, value in {'Authorization': 'Bearer ' + token,
                           'Content-Type': 'application/octet-stream',
                           'Content-Length': str(path.stat().st_size),
                           'User-Agent': 'VM-backup-migration',
                           'Accept': 'application/vnd.github+json'}.items():
            connection.putheader(key, value)
        connection.endheaders()
        with path.open('rb') as f:
            while block := f.read(4 * 1024 * 1024):
                connection.send(block)
        response = connection.getresponse()
        body = response.read()
        if response.status != 201:
            raise RuntimeError(f'Asset upload returned HTTP {response.status}')
        return json.loads(body)
    finally:
        connection.close()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def verify_asset(token, asset, expected):
    if asset['size'] != expected['size']:
        raise RuntimeError('Remote asset size mismatch')
    if asset.get('digest'):
        if asset['digest'] != 'sha256:' + expected['sha256']:
            raise RuntimeError('Remote SHA-256 mismatch')
        return
    request = urllib.request.Request(asset['url'], headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/octet-stream',
        'User-Agent': 'VM-backup-migration'})
    h = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=600) as response:
        while block := response.read(4 * 1024 * 1024):
            h.update(block)
    if h.hexdigest() != expected['sha256']:
        raise RuntimeError('Remote download SHA-256 mismatch')


def main():
    verification_path = BASE.parent / 'private/verification.json'
    verification = json.loads(verification_path.read_text())
    if verification.get('missing_members') or verification.get('aes_gcm_authentication') != 'passed':
        raise RuntimeError('Local backup verification has not passed')
    manifest = json.loads((ASSETS / 'manifest.json').read_text())
    paths = [ASSETS / chunk['name'] for chunk in manifest['chunks']] + [ASSETS / 'manifest.json']
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f'Missing asset: {path.name}')
    token = (os.environ.get('VM_BACKUP_GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
             or os.environ.get('GITHUB_TOKEN'))
    if not token and shutil.which('gh'):
        auth = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True)
        if auth.returncode == 0:
            token = auth.stdout.strip()
    token = token or getpass.getpass('GitHub token (hidden): ')
    if not token:
        raise RuntimeError('No token supplied')
    repo = api(token, f'/repos/{REPO}')
    if not repo.get('permissions', {}).get('push'):
        raise RuntimeError('Token does not have write access to the destination')
    env = os.environ.copy()
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
                'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
                'GIT_CONFIG_VALUE_0': 'Authorization: Basic ' +
                base64.b64encode(('x-access-token:' + token).encode()).decode()})
    def git(*args):
        subprocess.run(['git', *args], cwd=BASE, env=env, check=True)
    if not (BASE / '.git').exists():
        git('init', '-b', 'main')
        git('remote', 'add', 'origin', f'https://github.com/{REPO}.git')
    git('config', 'user.name', 'xuzinann')
    git('config', 'user.email', 'xuzinann@users.noreply.github.com')
    git('add', '.gitignore', 'README.md', 'restore.py', 'requirements.txt', 'upload_backup.py', 'manifest.json', 'verification.json')
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=BASE, env=env)
    if changed.returncode == 1:
        git('commit', '-m', 'Add encrypted VM migration backup and restoration tools')
    elif changed.returncode != 0:
        raise RuntimeError('Cannot inspect staged changes')
    git('push', '-u', 'origin', 'main')
    try:
        release = api(token, f'/repos/{REPO}/releases/tags/{TAG}')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # Draft releases may not be returned by the tag endpoint.
        existing = api(token, f'/repos/{REPO}/releases?per_page=100')
        release = next((r for r in existing if r['tag_name'] == TAG), None)
        if release is None:
            release = api(token, f'/repos/{REPO}/releases', 'POST', {
                'tag_name': TAG, 'target_commitish': 'main', 'name': 'Encrypted VM migration backup',
                'draft': True, 'body': 'Encrypted filesystem archive. Download all chunks and manifest.json. '
                'Keep the decryption key separately. See README for verification and staged restoration.'})
    for path in paths:
        expected = {'size': path.stat().st_size, 'sha256': digest(path)}
        for attempt in range(4):
            assets = api(token, f'/repos/{REPO}/releases/{release["id"]}/assets?per_page=100')
            asset = next((a for a in assets if a['name'] == path.name), None)
            if asset and asset.get('state') == 'uploaded':
                verify_asset(token, asset, expected)
                print(f'Verified remote asset: {path.name}', flush=True)
                break
            if asset:
                # Only our incomplete release asset of the exact name is removed.
                api(token, f'/repos/{REPO}/releases/assets/{asset["id"]}', 'DELETE')
            try:
                asset = upload(token, release['id'], path)
                verify_asset(token, asset, expected)
                print(f'Uploaded and verified: {path.name}', flush=True)
                break
            except (OSError, http.client.HTTPException) as e:
                if attempt == 3:
                    raise
                print(f'Retrying {path.name} after {type(e).__name__}', flush=True)
                time.sleep(3)
        else:
            raise RuntimeError(f'Failed asset: {path.name}')
    release = api(token, f'/repos/{REPO}/releases/{release["id"]}', 'PATCH', {'draft': False})
    print('Backup published and all remote assets verified: ' + release['html_url'])


if __name__ == '__main__':
    main()
