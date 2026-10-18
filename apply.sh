#!/usr/bin/env bash
# Merge WhatsApp text history from an iOS/Mac ChatStorage.sqlite into WhatsApp on a rooted Android phone.
#   ./apply.sh /path/to/ChatStorage.sqlite     merge (keeps a backup of the phone's database in ./run-*/)
#   ./apply.sh --restore ./run-YYYYmmdd-HHMMSS  put that backup back
set -euo pipefail

D=/data/data/com.whatsapp/databases
T=/data/local/tmp

push_db() {  # push a local msgstore.db into WhatsApp with the right owner, mode and SELinux label
  local owner
  owner=$(adb shell "su -c 'stat -c %u:%g $D/msgstore.db'" | tr -d '\r')
  adb push "$1" "$T/wa-msgstore.db" >/dev/null
  adb shell "su -c 'am force-stop com.whatsapp; cp $T/wa-msgstore.db $D/msgstore.db && rm -f $D/msgstore.db-wal $D/msgstore.db-shm && chown $owner $D/msgstore.db && chmod 600 $D/msgstore.db && restorecon $D/msgstore.db; rm -f $T/wa-msgstore.db'"
}

if [ "${1:-}" = "--restore" ]; then
  push_db "${2:?usage: ./apply.sh --restore ./run-dir}/msgstore.backup.db"
  echo "Restored the backup from $2. Open WhatsApp."
  exit 0
fi

IOS=${1:?usage: ./apply.sh /path/to/ChatStorage.sqlite}
OUT=./run-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
cp "$IOS" "$OUT/ChatStorage.sqlite"

# 1. stop WhatsApp and pull its current database (WAL included, so nothing received tonight is lost)
adb shell "su -c 'am force-stop com.whatsapp; rm -rf $T/wam; mkdir $T/wam; cp $D/msgstore.db* $T/wam/; chmod -R 755 $T/wam'"
adb pull "$T/wam/." "$OUT/" >/dev/null
adb shell "su -c 'rm -rf $T/wam'"
sqlite3 "$OUT/msgstore.db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
rm -f "$OUT"/msgstore.db-wal "$OUT"/msgstore.db-shm
cp "$OUT/msgstore.db" "$OUT/msgstore.backup.db"

# 2. merge on the computer
python3 "$(dirname "$0")/wa_ios_to_android.py" "$OUT/ChatStorage.sqlite" "$OUT/msgstore.db"
sqlite3 "$OUT/msgstore.db" "PRAGMA journal_mode=DELETE;" >/dev/null

# 3. put it back
push_db "$OUT/msgstore.db"
echo "Done. Open WhatsApp. To undo: ./apply.sh --restore $OUT"
