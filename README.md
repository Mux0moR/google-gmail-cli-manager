# 📬 Gmail CLI

Небольшое CLI-приложение для управления Gmail через OAuth2.

## ✨ Возможности

- 📥 **Список писем** (с `--query`)
- 📖 **Чтение письма** по `id`
- ✉️ **Отправка письма** (в т.ч. с вложениями)
- 🗑️ **Перемещение в корзину**
- ✅ **Прочитано / непрочитано**
- 🧹 **Массовые операции** по фильтру (по умолчанию **dry-run**)
- 📎 **Скачивание вложений**

## 🧰 Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 🚀 Быстрый старт

Файл OAuth credentials уже находится в каталоге проекта.

Первый запуск откроет браузер для авторизации Google и создаст `token.json`.

### 📥 Список писем

```bash
python3 gmail_cli.py list --max 10
```

С фильтром (Gmail query):

```bash
python3 gmail_cli.py list --query "is:unread label:inbox" --max 20
```

### 📖 Прочитать письмо

```bash
python3 gmail_cli.py read --id MESSAGE_ID
```

### ✉️ Отправить письмо

```bash
python3 gmail_cli.py send --to user@example.com --subject "Тема" --body "Текст письма"
```

С вложениями 📎:

```bash
python3 gmail_cli.py send --to user@example.com --subject "Тема" --body "Текст" --attach ./a.pdf --attach ./b.png
```

### 🗑️ В корзину

```bash
python3 gmail_cli.py trash --id MESSAGE_ID
```

### ✅ Прочитано/непрочитано

```bash
python3 gmail_cli.py mark-read --id MESSAGE_ID
python3 gmail_cli.py mark-unread --id MESSAGE_ID
```

### 🧹 Массовые операции (по query)

По умолчанию это **dry-run** (ничего не меняет) — сначала показывает список кандидатов.

```bash
python3 gmail_cli.py bulk-mark-read --query "is:unread label:inbox" --max 50
```

Применить изменения (⚠️ реально меняет почту):

```bash
python3 gmail_cli.py bulk-mark-read --query "is:unread label:inbox" --max 50 --apply
python3 gmail_cli.py bulk-trash --query "older_than:30d is:unread" --max 100 --apply
```

### 🧽 Удалить (в корзину) письма от определённого отправителя

Сначала посмотрите, какие письма попадут под фильтр (dry-run, ничего не меняет):

```bash
python3 gmail_cli.py bulk-trash --query "from:sender@example.com" --max 100
```

Переместить их в корзину 🗑️:

```bash
python3 gmail_cli.py bulk-trash --query "from:sender@example.com" --max 100 --apply
```

### 🧽 Удалить (в корзину) письма которым более 180 дней

Сначала посмотрите, какие письма попадут под фильтр (dry-run, ничего не меняет):

```bash
python3 gmail_cli.py bulk-trash --query "older_than:180d" --max 500
```

Переместить их в корзину 🗑️ письма которым более 180 дней:

```bash
python3 gmail_cli.py bulk-trash --query "older_than:180d" --max 500 --apply
```

Полезные варианты `--query`:

- Только входящие: `from:sender@example.com label:inbox`
- Только непрочитанные: `from:sender@example.com is:unread`
- Старше 30 дней: `from:sender@example.com older_than:30d`

Важно: `bulk-trash` перемещает письма в **Корзину**, а не удаляет навсегда.

### 📎 Вложения: скачать из письма

```bash
python3 gmail_cli.py attachments-download --id MESSAGE_ID --out-dir ./attachments
```

## 🔐 Безопасность

- Не публикуйте `token.json` и OAuth credentials.
- Файлы `client_secret_*.json` содержат `client_secret` — держите их **вне репозитория**.
- При необходимости задавайте пути к файлам явно:

```bash
python3 gmail_cli.py --credentials-file /path/to/client_secret.json --token-file /path/to/token.json list
```

## 🧯 Частые проблемы

Если при авторизации видите `Ошибка 403: access_denied` и текст про “только одобренные тестировщики”, это значит OAuth-приложение в режиме **Testing** и ваш аккаунт не добавлен в `Test users`.
