"""Merge text history from a WhatsApp Mac/iOS ChatStorage.sqlite into an Android msgstore.db (text + links).
usage: python3 wa_ios_to_android.py <ChatStorage.sqlite> <msgstore.db (a copy; modified in place)>
"""
import sqlite3, sys

APPLE_EPOCH = 978307200
TEXT_TYPES = (0, 7)            # iOS: 0 text, 7 text with link preview -> Android type 0
CHAT_SESSION_TYPES = (0, 1, 4) # 1:1, group, community-group; skips broadcast/status/newsletter


def jid_parts(raw):
    user, _, server = raw.partition("@")
    return user, server


def main(ios_path, and_path):
    ios = sqlite3.connect(f"file:{ios_path}?mode=ro", uri=True)
    db = sqlite3.connect(and_path)
    db.execute("PRAGMA foreign_keys=OFF")
    cur = db.cursor()

    # native jid.type for ordinary contacts/groups (type 7 on s.whatsapp.net is the account's own jid: never reuse)
    type_for = {"s.whatsapp.net": 0, "lid": 18, "g.us": 1}
    jid_cache = {}

    def jid_row(raw, create=True):
        if raw in jid_cache:
            return jid_cache[raw]
        r = cur.execute("SELECT _id FROM jid WHERE raw_string=?", (raw,)).fetchone()
        if r is None:
            if not create:
                return None
            user, server = jid_parts(raw)
            cur.execute("INSERT INTO jid(user, server, agent, device, type, raw_string) VALUES (?,?,0,0,?,?)",
                        (user, server, type_for.get(server, 0), raw))
            r = (cur.lastrowid,)
        jid_cache[raw] = r[0]
        return r[0]

    def linked_rows(jrow):
        """The jid row plus its phone<->lid twins from jid_map."""
        rows = {jrow}
        rows |= {r[0] for r in cur.execute("SELECT lid_row_id FROM jid_map WHERE jid_row_id=?", (jrow,))}
        rows |= {r[0] for r in cur.execute("SELECT jid_row_id FROM jid_map WHERE lid_row_id=?", (jrow,))}
        return rows

    def lid_of(jrow):
        """Current WhatsApp addresses people by LID; swap a phone jid row for its LID twin when known."""
        r = cur.execute("SELECT lid_row_id FROM jid_map WHERE jid_row_id=?", (jrow,)).fetchone()
        return r[0] if r else jrow

    preexisting_msgs ={r[0] for r in cur.execute("SELECT DISTINCT chat_row_id FROM message")}

    # ---- map iOS chat sessions -> Android chat rows
    sessions = ios.execute(
        f"SELECT Z_PK, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE, ZARCHIVED FROM ZWACHATSESSION "
        f"WHERE ZSESSIONTYPE IN {CHAT_SESSION_TYPES} AND ZCONTACTJID IS NOT NULL").fetchall()
    chat_for_session, created_chats = {}, set()
    for pk, raw, name, stype, archived in sessions:
        jrow = jid_row(raw)
        cands = linked_rows(jrow)
        q = f"SELECT _id, jid_row_id FROM chat WHERE jid_row_id IN ({','.join('?' * len(cands))})"
        existing = cur.execute(q, tuple(cands)).fetchone()
        if existing:
            chat_for_session[pk] = existing[0]
            continue
        # prefer a lid row (what current WhatsApp uses for 1:1) if one is linked
        target = jrow
        for c in cands:
            srv = cur.execute("SELECT server FROM jid WHERE _id=?", (c,)).fetchone()[0]
            if srv == "lid":
                target = c
        cur.execute("INSERT INTO chat(jid_row_id, hidden, subject, archived, created_timestamp, sort_timestamp) "
                    "VALUES (?,0,?,?,0,0)", (target, name if stype in (1, 4) else None, int(archived or 0)))
        chat_for_session[pk] = cur.lastrowid
        created_chats.add(cur.lastrowid)

    member_jid = dict(ios.execute("SELECT Z_PK, ZMEMBERJID FROM ZWAGROUPMEMBER"))
    session_type = {pk: st for pk, _, _, st, _ in sessions}

    rows = ios.execute(
        f"SELECT Z_PK, ZCHATSESSION, ZISFROMME, ZSTANZAID, ZGROUPMEMBER, ZFROMJID, ZMESSAGEDATE, ZTEXT, ZSTARRED "
        f"FROM ZWAMESSAGE WHERE ZMESSAGETYPE IN {TEXT_TYPES} AND ZTEXT IS NOT NULL AND ZTEXT != '' "
        f"AND ZMESSAGEDATE IS NOT NULL ORDER BY ZMESSAGEDATE, Z_PK").fetchall()
    rows = [r for r in rows if r[1] in chat_for_session]

    # ---- make room: old messages take sort_id 1..N, existing (newer) ones shift above them
    offset = len(rows) + 10
    cur.execute("UPDATE message SET sort_id = sort_id + ? WHERE sort_id > 0", (offset,))
    for col in ("last_read_message_sort_id", "display_message_sort_id", "last_message_sort_id",
                "last_read_receipt_sent_message_sort_id"):
        cur.execute(f"UPDATE chat SET {col} = {col} + ? WHERE {col} > 0", (offset,))

    inserted, skipped = 0, 0
    newest = {}  # chat_row_id -> (ts, msg_id, sort_id)
    oldest = {}  # chat_row_id -> ts
    for sort_id, (pk, sess, from_me, stanza, gm, from_jid, mdate, text, starred) in enumerate(rows, 1):
        chat = chat_for_session[sess]
        ts = int((mdate + APPLE_EPOCH) * 1000)
        sender = 0
        if not from_me and session_type[sess] in (1, 4):
            raw = member_jid.get(gm) or (from_jid if from_jid and not from_jid.endswith("@g.us") else None)
            sender = lid_of(jid_row(raw)) if raw else 0
        key = stanza or f"MIGRATED{pk:012d}"
        cur.execute(
            "INSERT OR IGNORE INTO message(chat_row_id, from_me, key_id, sender_jid_row_id, status, broadcast, "
            "origin, timestamp, received_timestamp, receipt_server_timestamp, message_type, text_data, starred, "
            "lookup_tables, sort_id) VALUES (?,?,?,?,?,0,0,?,?,-1,0,?,?,0,?)",
            (chat, int(from_me or 0), key, sender, 13 if from_me else 0, ts, ts, text, int(starred or 0), sort_id))
        if cur.rowcount == 0:
            skipped += 1
            continue
        inserted += 1
        newest[chat] = (ts, cur.lastrowid, sort_id)
        oldest.setdefault(chat, ts)

    # ---- point chats with no newer messages at their newest migrated message
    for chat, (ts, mid, sid) in newest.items():
        if chat in preexisting_msgs:
            continue
        cur.execute("UPDATE chat SET last_message_row_id=?, display_message_row_id=?, last_read_message_row_id=?, "
                    "last_message_sort_id=?, display_message_sort_id=?, last_read_message_sort_id=?, "
                    "sort_timestamp=?, unseen_message_count=0, unseen_row_count=0 WHERE _id=?",
                    (mid, mid, mid, sid, sid, sid, ts, chat))
        cur.execute("UPDATE chat SET created_timestamp=? WHERE _id=? AND created_timestamp=0",
                    (oldest[chat], chat))

    # ---- renumber the whole timeline by real time so offline-delivered messages interleave correctly
    cur.execute("CREATE TEMP TABLE rn AS SELECT _id, row_number() OVER (ORDER BY timestamp, _id) n FROM message")
    cur.execute("UPDATE message SET sort_id = (SELECT n FROM rn WHERE rn._id = message._id)")
    for row_col, sort_col in (("last_message_row_id", "last_message_sort_id"),
                              ("display_message_row_id", "display_message_sort_id"),
                              ("last_read_message_row_id", "last_read_message_sort_id"),
                              ("last_read_receipt_sent_message_row_id", "last_read_receipt_sent_message_sort_id")):
        cur.execute(f"UPDATE chat SET {sort_col} = (SELECT sort_id FROM message WHERE _id = chat.{row_col}) "
                    f"WHERE {row_col} > 0 AND EXISTS (SELECT 1 FROM message WHERE _id = chat.{row_col})")

    db.commit()
    print(f"sessions mapped: {len(chat_for_session)} (new chats created: {len(created_chats)})")
    print(f"text messages inserted: {inserted}, skipped as duplicates: {skipped}")
    print("integrity:", db.execute("PRAGMA integrity_check").fetchone()[0])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
