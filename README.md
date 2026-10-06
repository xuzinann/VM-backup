# Encrypted VM migration backup

This repository holds restoration tools and a public ciphertext manifest. The encrypted filesystem archive is attached to the `vm-backup-20261005` GitHub Release in ordered 512 MiB chunks. No decryption key is committed or uploaded.

The source backup was verified locally: 31 encrypted chunks totaling 15.43 GiB, 629,777 tar entries scanned, all 79 required application/snapshot members found, and all 63 SQLite snapshots passed integrity checks. Runtime sockets were omitted and a live Hermes directory changed during capture. See `verification.json`. Release availability depends on the upload completing successfully.

## Keep the key separately

The source VM key is `/root/vm-backup-20261005.key`. Copy it to a password manager or another private machine before deleting the old VM. The backup cannot be recovered without it. Never commit the key or put it in a GitHub issue, release, or chat.

## Coverage

The archive includes persistent files from the source VM: root home, project working trees and Git history, Python/Node environments, agent profiles and memories, credentials, SQLite files, logs, `/etc`, systemd units, crontabs, `/usr`, `/usr/local`, `/var`, `/home`, and `/boot`. Credentials and personal data exist only inside the encrypted archive.

Excluded: `/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/mnt`, `/media`, `/lost+found`, top-level swap files, the backup output directory, and the separate decryption key. If persistent data exists on excluded mounts, it needs a separate backup. This is a live file backup, not a bootable disk image or one atomic snapshot of all applications.

The `private/` folder inside the archive contains package versions, service states, disk/mount inventory, root crontab, coverage details, and independently consistent SQLite snapshots. Each successful SQLite snapshot passed `PRAGMA quick_check`. Failed snapshots, if any, are recorded in `private/sqlite-snapshots.json`; original database/WAL files are still in the filesystem archive.

## Download and verify on the new VM

Use a fresh Debian 13 x86_64 VM, preferably with at least 8 GiB RAM and 100 GiB free disk for staging. Download every release asset into one `assets/` directory, including `manifest.json`. If GitHub CLI is installed:

```sh
git clone https://github.com/xuzinann/VM-backup.git
cd VM-backup
gh release download vm-backup-20261005 --repo xuzinann/VM-backup --dir assets
python3 -m venv restore-venv
restore-venv/bin/pip install -r requirements.txt
restore-venv/bin/python restore.py --assets assets --key /private/path/vm-backup-20261005.key --output /private/path/vm-files.tar.gz --check-tar
mkdir -m 700 /private/path/staging
tar --acls --xattrs --numeric-owner -xzf /private/path/vm-files.tar.gz -C /private/path/staging
```

`restore.py` verifies each encrypted chunk's SHA-256 and authenticates the complete AES-256-GCM stream before making the decrypted archive available. It never extracts files or starts bots automatically. The ciphertext manifest can reveal archive size and timing, but not archived filenames or credentials.

## Restore applications carefully

1. Inspect `staging/private/` for inventory and snapshot failures. Recover application files from `staging/root/` and selected service definitions from `staging/etc/`.
2. Reinstall required OS packages using the saved inventory. Existing environments are retained, but rebuild them if their interpreters or native libraries are incompatible with the new VM. Do not copy old `/usr`, boot files, disk mappings, machine ID, cloud-init state, network settings, or SSH host keys over a running fresh VM.
3. Restore successful database snapshots from `staging/private/sqlite-snapshots/` to their corresponding application paths while those applications are stopped. Move aside stale `-wal` and `-shm` files before using a snapshot. Keep extraction permissions private.
4. Preserve SSH access to the new VM, adjust exchange API IP allowlists, and confirm credentials and external API connectivity.
5. Inspect cron enablement and service definitions before activating them. Archived enablement symlinks and saved scheduler jobs can start work when restored; do not activate them during staging.
6. Stop the old trading services before starting trading on the new VM. Confirm balances, positions, and open orders against the exchange; reconcile exchange state before allowing new orders. Run only one execution instance per account/strategy.
7. The backup reflects its capture time. Take a final database/config delta before cutover if the old VM continues running after this backup.

## Upload from the source VM

`upload_backup.py` prompts for a GitHub token without echoing it. Use a fine-grained token restricted to `xuzinann/VM-backup` with Contents read/write permission. It pushes only the named restoration files and encrypted manifest, uploads ciphertext as release assets, checks their SHA-256 digests, then publishes the release. It never uploads the decryption key or private inventory in plaintext.
