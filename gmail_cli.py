#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import pathlib
import re
import sys
import textwrap
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _autodetect_credentials_file() -> Optional[str]:
    for name in os.listdir("."):
        if name.startswith("client_secret_") and name.endswith(".json"):
            return name
    return None


def load_service(
    credentials_file: Optional[str] = None,
    token_file: str = "token.json",
):
    if not credentials_file:
        credentials_file = _autodetect_credentials_file()
    if not credentials_file or not os.path.exists(credentials_file):
        raise FileNotFoundError(credentials_file or "client_secret_*.json")

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _headers_to_dict(message: Dict[str, Any]) -> Dict[str, str]:
    return {
        h["name"].lower(): h["value"]
        for h in message.get("payload", {}).get("headers", [])
    }


def list_message_ids(service, query: str, max_results: int) -> List[str]:
    ids: List[str] = []
    page_token = None
    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query or "",
                maxResults=min(500, max_results - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        for msg in response.get("messages", []) or []:
            ids.append(msg["id"])
            if len(ids) >= max_results:
                return ids
        page_token = response.get("nextPageToken")
        if not page_token:
            return ids


def get_message_metadata(service, message_id: str) -> Dict[str, Any]:
    meta = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        )
        .execute()
    )
    headers = _headers_to_dict(meta)
    return {
        "id": meta["id"],
        "thread_id": meta.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(без темы)"),
        "date": headers.get("date", ""),
        "snippet": meta.get("snippet", ""),
        "label_ids": meta.get("labelIds", []),
    }


def list_messages(service, max_results: int, query: str = "") -> List[Dict[str, Any]]:
    ids = list_message_ids(service, query=query, max_results=max_results)
    return [get_message_metadata(service, message_id=i) for i in ids]


def get_message(service, message_id: str) -> Dict[str, Any]:
    full = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = _headers_to_dict(full)

    body = ""
    payload = full.get("payload", {})
    parts = payload.get("parts", [])

    if "body" in payload and payload["body"].get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="ignore"
        )
    else:
        for part in parts:
            if part.get("mimeType") in ("text/plain", "text/html"):
                data = part.get("body", {}).get("data")
                if data:
                    body = base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="ignore"
                    )
                    break

    return {
        "id": full["id"],
        "thread_id": full.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(без темы)"),
        "date": headers.get("date", ""),
        "snippet": full.get("snippet", ""),
        "body": body.strip(),
        "label_ids": full.get("labelIds", []),
    }


def send_message(
    service,
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    for path in attachments or []:
        p = pathlib.Path(path)
        data = p.read_bytes()
        mime, _ = mimetypes.guess_type(str(p))
        if mime and "/" in mime:
            maintype, subtype = mime.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=p.name,
        )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )


def trash_message(service, message_id: str) -> Dict[str, Any]:
    return service.users().messages().trash(userId="me", id=message_id).execute()


def modify_message_labels(
    service,
    message_id: str,
    add_label_ids: Optional[List[str]] = None,
    remove_label_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    body = {
        "addLabelIds": add_label_ids or [],
        "removeLabelIds": remove_label_ids or [],
    }
    return (
        service.users()
        .messages()
        .modify(userId="me", id=message_id, body=body)
        .execute()
    )


def batch_modify_messages(
    service,
    message_ids: List[str],
    add_label_ids: Optional[List[str]] = None,
    remove_label_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    body = {
        "ids": message_ids,
        "addLabelIds": add_label_ids or [],
        "removeLabelIds": remove_label_ids or [],
    }
    return service.users().messages().batchModify(userId="me", body=body).execute()


def _sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1F]+", "_", name)
    name = name.replace("\n", "_").replace("\r", "_")
    if not name:
        return "attachment"
    return name[:255]


def iter_parts(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    stack = [payload]
    while stack:
        p = stack.pop()
        yield p
        for child in p.get("parts", []) or []:
            stack.append(child)


def list_attachments_from_message(full_message: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = full_message.get("payload", {}) or {}
    attachments: List[Dict[str, Any]] = []
    for part in iter_parts(payload):
        filename = part.get("filename") or ""
        body = part.get("body", {}) or {}
        attachment_id = body.get("attachmentId")
        if filename and attachment_id:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": part.get("mimeType", ""),
                    "attachment_id": attachment_id,
                    "size": body.get("size"),
                }
            )
    return attachments


def download_attachments(
    service,
    message_id: str,
    out_dir: str,
    only_mime: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    out_path = pathlib.Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    full = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    attachments = list_attachments_from_message(full)
    saved: List[Dict[str, Any]] = []

    for a in attachments:
        if only_mime and a.get("mime_type") != only_mime:
            continue
        if max_bytes is not None and a.get("size") and int(a["size"]) > max_bytes:
            continue

        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=a["attachment_id"])
            .execute()
        )
        data_b64 = att.get("data")
        if not data_b64:
            continue
        data = base64.urlsafe_b64decode(data_b64.encode("utf-8"))
        filename = _sanitize_filename(a["filename"])
        target = out_path / filename
        target.write_bytes(data)
        saved.append(
            {
                "filename": filename,
                "path": str(target),
                "mime_type": a.get("mime_type", ""),
                "bytes": len(data),
            }
        )
    return saved


def print_json(data: Any):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI для управления Gmail")
    parser.add_argument(
        "--credentials-file",
        default=None,
        help="Путь к OAuth credentials JSON",
    )
    parser.add_argument(
        "--token-file",
        default="token.json",
        help="Файл для хранения access/refresh токенов",
    )

    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="Список писем")
    list_parser.add_argument("--max", type=int, default=10, help="Максимум писем")
    list_parser.add_argument(
        "--query",
        default="",
        help='Gmail query, например: "is:unread label:inbox"',
    )

    read_parser = subparsers.add_parser("read", help="Прочитать письмо")
    read_parser.add_argument("--id", required=True, help="ID письма")

    send_parser = subparsers.add_parser("send", help="Отправить письмо")
    send_parser.add_argument("--to", required=True, help="Email получателя")
    send_parser.add_argument("--subject", required=True, help="Тема письма")
    send_parser.add_argument("--body", required=True, help="Текст письма")
    send_parser.add_argument(
        "--attach",
        action="append",
        default=[],
        help="Путь к файлу-вложению (можно указать несколько раз)",
    )

    trash_parser = subparsers.add_parser("trash", help="Переместить письмо в корзину")
    trash_parser.add_argument("--id", required=True, help="ID письма")

    mark_read = subparsers.add_parser("mark-read", help="Пометить как прочитанное")
    mark_read.add_argument("--id", required=True, help="ID письма")

    mark_unread = subparsers.add_parser("mark-unread", help="Пометить как непрочитанное")
    mark_unread.add_argument("--id", required=True, help="ID письма")

    bulk_trash = subparsers.add_parser(
        "bulk-trash", help="Массово переместить письма в корзину (по query)"
    )
    bulk_trash.add_argument("--query", default="", help="Gmail query")
    bulk_trash.add_argument("--max", type=int, default=50, help="Лимит писем")
    bulk_trash.add_argument(
        "--apply",
        action="store_true",
        help="Выполнить действие (без этого флага будет dry-run)",
    )

    bulk_mark_read = subparsers.add_parser(
        "bulk-mark-read", help="Массово пометить прочитанными (по query)"
    )
    bulk_mark_read.add_argument("--query", default="", help="Gmail query")
    bulk_mark_read.add_argument("--max", type=int, default=200, help="Лимит писем")
    bulk_mark_read.add_argument(
        "--apply",
        action="store_true",
        help="Выполнить действие (без этого флага будет dry-run)",
    )

    bulk_mark_unread = subparsers.add_parser(
        "bulk-mark-unread", help="Массово пометить непрочитанными (по query)"
    )
    bulk_mark_unread.add_argument("--query", default="", help="Gmail query")
    bulk_mark_unread.add_argument("--max", type=int, default=200, help="Лимит писем")
    bulk_mark_unread.add_argument(
        "--apply",
        action="store_true",
        help="Выполнить действие (без этого флага будет dry-run)",
    )

    att_dl = subparsers.add_parser(
        "attachments-download", help="Скачать вложения из письма"
    )
    att_dl.add_argument("--id", required=True, help="ID письма")
    att_dl.add_argument("--out-dir", default="attachments", help="Папка для сохранения")
    att_dl.add_argument(
        "--only-mime", default=None, help="Скачать только указанный mimeType"
    )
    att_dl.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Скачать только вложения не больше этого размера",
    )

    return parser


def _bulk_preview(service, query: str, max_results: int) -> Tuple[List[str], List[Dict[str, Any]]]:
    ids = list_message_ids(service, query=query, max_results=max_results)
    previews = [get_message_metadata(service, message_id=i) for i in ids]
    return ids, previews


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main():
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        print(
            "\nПримеры:\n"
            "  python3 gmail_cli.py list --max 10\n"
            "  python3 gmail_cli.py list --query \"is:unread label:inbox\" --max 20\n"
            "  python3 gmail_cli.py read --id MESSAGE_ID\n"
            "  python3 gmail_cli.py send --to user@example.com --subject \"Тема\" --body \"Текст\"\n"
            "  python3 gmail_cli.py send --to user@example.com --subject \"Тема\" --body \"Текст\" --attach ./file.pdf\n"
            "  python3 gmail_cli.py trash --id MESSAGE_ID\n"
            "  python3 gmail_cli.py mark-read --id MESSAGE_ID\n"
            "  python3 gmail_cli.py bulk-mark-read --query \"is:unread\" --max 50\n"
            "  python3 gmail_cli.py bulk-mark-read --query \"is:unread\" --max 50 --apply\n"
            "\nУдалить (в корзину) письма от отправителя:\n"
            "  python3 gmail_cli.py bulk-trash --query \"from:sender@example.com\" --max 100\n"
            "  python3 gmail_cli.py bulk-trash --query \"from:sender@example.com\" --max 100 --apply\n"
            "  python3 gmail_cli.py bulk-trash --query \"from:sender@example.com is:unread\" --max 100 --apply\n"
            "  python3 gmail_cli.py attachments-download --id MESSAGE_ID --out-dir ./attachments"
        )
        raise SystemExit(0)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        raise SystemExit(2)

    try:
        if args.command == "send":
            missing = [p for p in (args.attach or []) if not pathlib.Path(p).exists()]
            if missing:
                print_json(
                    {
                        "error": "attachment_not_found",
                        "missing": missing,
                        "hint": "Проверьте путь(и) в --attach или используйте абсолютный путь.",
                    }
                )
                raise SystemExit(2)

        service = load_service(
            credentials_file=args.credentials_file,
            token_file=args.token_file,
        )

        if args.command == "list":
            messages = list_messages(service, max_results=args.max, query=args.query)
            print_json(messages)
            return

        if args.command == "read":
            message = get_message(service, message_id=args.id)
            print_json(message)
            return

        if args.command == "send":
            sent = send_message(
                service,
                to_email=args.to,
                subject=args.subject,
                body=args.body,
                attachments=args.attach,
            )
            print_json({"status": "sent", "id": sent.get("id")})
            return

        if args.command == "trash":
            trashed = trash_message(service, message_id=args.id)
            print_json({"status": "trashed", "id": trashed.get("id")})
            return

        if args.command == "mark-read":
            res = modify_message_labels(service, message_id=args.id, remove_label_ids=["UNREAD"])
            print_json({"status": "marked_read", "id": res.get("id")})
            return

        if args.command == "mark-unread":
            res = modify_message_labels(service, message_id=args.id, add_label_ids=["UNREAD"])
            print_json({"status": "marked_unread", "id": res.get("id")})
            return

        if args.command in ("bulk-mark-read", "bulk-mark-unread", "bulk-trash"):
            ids, previews = _bulk_preview(service, query=args.query, max_results=args.max)
            print_json(
                {
                    "dry_run": not args.apply,
                    "query": args.query,
                    "count": len(ids),
                    "messages": previews,
                }
            )
            if not args.apply:
                return

            if not ids:
                print_json({"status": "ok", "count": 0})
                return

            if args.command == "bulk-mark-read":
                for chunk in _chunked(ids, 1000):
                    batch_modify_messages(service, message_ids=chunk, remove_label_ids=["UNREAD"])
                print_json({"status": "bulk_marked_read", "count": len(ids)})
                return

            if args.command == "bulk-mark-unread":
                for chunk in _chunked(ids, 1000):
                    batch_modify_messages(service, message_ids=chunk, add_label_ids=["UNREAD"])
                print_json({"status": "bulk_marked_unread", "count": len(ids)})
                return

            if args.command == "bulk-trash":
                trashed = 0
                for idx, mid in enumerate(ids, start=1):
                    trash_message(service, message_id=mid)
                    trashed += 1
                    if idx % 25 == 0:
                        sys.stderr.write(f"Progress: {idx}/{len(ids)} trashed...\n")
                print_json({"status": "bulk_trashed", "count": trashed})
                return

        if args.command == "attachments-download":
            saved = download_attachments(
                service,
                message_id=args.id,
                out_dir=args.out_dir,
                only_mime=args.only_mime,
                max_bytes=args.max_bytes,
            )
            print_json({"status": "downloaded", "count": len(saved), "files": saved})
            return
    except KeyboardInterrupt:
        sys.stderr.write(
            textwrap.dedent(
                """

                Операция прервана (Ctrl+C).
                """
            ).lstrip()
        )
        raise SystemExit(130)
    except FileNotFoundError as e:
        missing = getattr(e, "filename", None) or str(e)
        if missing == (args.credentials_file or "") or "client_secret_" in missing:
            parser.error(
                "Файл credentials не найден. Передайте корректный путь через --credentials-file."
            )
        print_json(
            {
                "error": "file_not_found",
                "path": missing,
                "hint": "Проверьте путь к файлу (например, вложение в --attach) и права доступа.",
            }
        )
        raise SystemExit(2)
    except HttpError as err:
        status = getattr(getattr(err, "resp", None), "status", None)
        details = str(err)
        hint = None
        if status == 403 and "access_denied" in details:
            hint = (
                "Похоже, OAuth-приложение в режиме Testing и ваш аккаунт не добавлен в Test users. "
                "В Google Cloud Console откройте OAuth consent screen и добавьте email в Test users "
                "или переведите приложение в Production."
            )
        payload = {"error": "gmail_api_error", "status": status, "details": details}
        if hint:
            payload["hint"] = hint
        print_json(payload)
        raise SystemExit(1)


if __name__ == "__main__":
    main()