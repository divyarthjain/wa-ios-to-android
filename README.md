# wa-ios-to-android

Move your **WhatsApp chat history from iPhone / WhatsApp for Mac to Android**, without a backup key, by writing it straight into WhatsApp's database on a **rooted** Android phone.

WhatsApp only restores backups within the same platform. This tool reads the iOS-format database (`ChatStorage.sqlite`) and merges it into the Android database (`msgstore.db`). Old chats show up in the right conversations, with the right senders and in the right order, mixed in with anything you've received since.

> **Status:** works for **text and link messages**. Media (photos, videos, voice notes, stickers) is not migrated yet. Tested on one device (see [Tested with](#tested-with)).

## When this helps

- You're switching from iPhone to Android and don't want to pay for a migration tool.
- **You lost your Android backup** (for example, you forgot the 64-digit key for an end-to-end encrypted backup) **but WhatsApp for Mac still has your chats.** The Mac app keeps its own full copy of your history in `ChatStorage.sqlite`, and that copy is not locked by the backup key.

## ⚠️ Read first

- **Root required** (Magisk, KernelSU, APatch…). Without root you can't write to WhatsApp's database.
- **Unofficial.** It edits WhatsApp's private database directly. A WhatsApp update can change the format and break this tool. Not affiliated with WhatsApp or Meta.
- **Your own data only.** Use it on your own account and your own chats.
- `apply.sh` **always keeps a backup** of the phone's database and can put it back with one command.
- **Don't clear WhatsApp's cache or storage afterwards.** WhatsApp may rebuild its database and drop the merged history. If that happens, just run the tool again.

## What gets migrated

| Migrated | Not yet |
|---|---|
| Text messages, messages with links | Photos, videos, voice notes, documents, stickers, GIFs |
| 1:1 chats and groups, including chats you no longer had on Android | Reactions, replies/quotes (they arrive as plain text), polls, calls |
| Who sent each group message | Status updates, broadcast lists, channels |
| Sent / received direction, timestamps, starred messages | Search: old messages may not show up in WhatsApp search |

## Requirements

- A **rooted** Android phone with **WhatsApp installed and registered** to your number (a fresh "Skip restore" setup is fine), and **USB debugging** on.
- On your computer: `adb`, `python3` (standard library only) and `sqlite3`.
- Your iOS-format `ChatStorage.sqlite`, from one of:
  - **WhatsApp for Mac:** `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`
  - **An unencrypted iPhone backup:** the file `ChatStorage.sqlite` in the domain `AppDomainGroup-group.net.whatsapp.WhatsApp.shared`.

## How to use

1. **Copy the Mac database first, before registering WhatsApp on Android.** Registering on a new phone logs WhatsApp for Mac out, and it may wipe its local data. Quit WhatsApp for Mac (Cmd+Q), then:
   ```sh
   cp -a ~/Library/Group\ Containers/group.net.whatsapp.WhatsApp.shared ~/wa-mac-copy
   ```
2. Set up WhatsApp on the Android phone (skipping the restore is fine) and let it finish its first sync.
3. Connect the phone with USB debugging on, and allow root access for **Shell** in your root manager.
4. Run:
   ```sh
   git clone https://github.com/divyarthjain/wa-ios-to-android
   cd wa-ios-to-android
   ./apply.sh ~/wa-mac-copy/ChatStorage.sqlite
   ```
5. Open WhatsApp. Your old chats should be there.

**Undo:** `./apply.sh --restore ./run-<timestamp>` puts the phone's original database back. The script prints the exact command at the end of each run.

## How it works

`apply.sh` stops WhatsApp, pulls `msgstore.db` (including its write-ahead log, so recent messages aren't lost), backs it up, runs the converter, then pushes the result back with the original file owner, mode and SELinux label.

`wa_ios_to_android.py` maps the iOS database onto the Android one:

| iOS (`ChatStorage.sqlite`) | Android (`msgstore.db`) |
|---|---|
| `ZWACHATSESSION.ZCONTACTJID` | `jid` row + `chat` row (an existing chat is reused) |
| `ZWAMESSAGE` (types 0 and 7) | `message` (type 0) |
| `ZWAGROUPMEMBER.ZMEMBERJID` | `message.sender_jid_row_id` |
| `ZMESSAGEDATE` (seconds since 2001) | `timestamp` (milliseconds since 1970) |
| `ZSTANZAID` | `key_id`, so a message that already exists isn't inserted twice |

Lessons from making it work, worth knowing if you change the code:

- **LIDs.** Current WhatsApp identifies people by a *LID* (`…@lid`) instead of their phone number (`…@s.whatsapp.net`). The `jid_map` table links the two. iOS data mostly uses phone numbers, so the converter routes chats and group senders through `jid_map` to the matching LID.
- **`jid.type` must be right.** Normal contacts use type `0` for phone numbers, `18` for LIDs and `1` for groups. **Type `7` is the account's own number.** Creating contact rows with type 7 made WhatsApp crash on start with a `NullPointerException`.
- **Order comes from `sort_id`, not `_id`.** Old messages are inserted after the new ones, so the whole timeline is renumbered by timestamp. The `chat.*_sort_id` pointers are updated to match.
- **Fresh installs already have chats.** A newly registered WhatsApp syncs your groups and recent messages from the server, so the converter merges into the existing chats rather than duplicating them.

## Troubleshooting

- **"WhatsApp keeps stopping":** run `./apply.sh --restore ./run-<timestamp>`, then capture the crash with `adb logcat -d -b crash` and open an issue (leave out any message content).
- **Old chats vanished later:** WhatsApp rebuilt its database, often after its cache or storage was cleared. Run `apply.sh` again.
- **`su: inaccessible or not found`:** grant root to *Shell* in your root manager.

## Tested with

| | Version |
|---|---|
| WhatsApp for Android | 2.26.40.76 |
| Android | 16 (AxionOS 2.9, Magisk 30.7) |
| WhatsApp for Mac (source database) | 26.38.74 |
| Result | about 89,000 text messages in 700 chats migrated, database integrity check OK |

## Roadmap

- [ ] Media: map `ZWAMEDIAITEM.ZMEDIALOCALPATH` to `message_media`, and copy the files into `Android/media/com.whatsapp/WhatsApp/Media/`
- [ ] Replies (`message_quoted`) and reactions
- [ ] Make old messages searchable (fill WhatsApp's search index)

PRs welcome. Please never attach real chat databases to issues.

## Credits

- The database layouts were worked out by inspecting the live databases on both platforms. [KnugiHK/Whatsapp-Chat-Exporter](https://github.com/KnugiHK/Whatsapp-Chat-Exporter) was a useful reference for both schemas.
- [ElDavoo/wa-crypt-tools](https://github.com/ElDavoo/wa-crypt-tools) is the tool for *encrypted* Android backups when you do have the key.

## License

MIT
