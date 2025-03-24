import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import os
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import redis

# Конфигурация
API_TOKEN = "..."
KYOCERA_PRINTER = "Kyocera2554"
HP_EMAIL = "d2ybqkm879@hpeprint.com"
EMAIL_FROM = "..."
EMAIL_PASSWORD = "..."
EMAIL_TO = "..."
REDIS_HOST = "redis"
REDIS_PORT = 6379

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Отправь мне документ (.pdf, .doc, .docx) или фото (.jpg).\n"
        "Команды:\n"
        "/kyocera_color_a3 - цветная печать на Kyocera (A3)\n"
        "/kyocera_color_a4 - цветная печать на Kyocera (A4)\n"
        "/kyocera_bw_a3 - ч/б печать на Kyocera (A3)\n"
        "/kyocera_bw_a4 - ч/б печать на Kyocera (A4)\n"
        "/hp_color - цветная печать на HP через email\n"
        "/hp_bw - ч/б печать на HP через email\n"
        "/kyocera_email_color_a3 - цветная печать на Kyocera через email (A3)\n"
        "/kyocera_email_color_a4 - цветная печать на Kyocera через email (A4)\n"
        "/kyocera_email_bw_a3 - ч/б печать на Kyocera через email (A3)\n"
        "/kyocera_email_bw_a4 - ч/б печать на Kyocera через email (A4)"
    )


async def convert_to_pdf(file_path: str, original_extension: str) -> str:
    if original_extension in [".doc", ".docx"]:
        output_file = file_path.replace(original_extension, ".pdf")
        try:
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    "/tmp",
                    file_path,
                ],
                check=True,
                timeout=30,
            )
            os.remove(file_path)
            return f"/tmp/{os.path.basename(output_file)}"
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка конвертации: {e}")
    return file_path


async def print_to_kyocera(file_path: str, color: bool, paper_size: str) -> str:
    color_option = "RGB" if color else "Grayscale"
    try:
        subprocess.run(
            [
                "lp",
                "-h",
                # "host.docker.internal:631",
                "93.183.81.123:631",
                "-d",
                KYOCERA_PRINTER,
                "-o",
                "fit-to-page",
                "-o",
                f"ColorModel={color_option}",
                "-o",
                f"media={paper_size}",
                file_path,
            ],
            check=True,
        )
        return f"Напечатано на Kyocera ({'цвет' if color else 'ч/б'}, {paper_size})!"
    except subprocess.CalledProcessError as e:
        return f"Ошибка печати: {e}"


async def send_to_email(
    to_email: str,
    file_path: str,
    file_extension: str,
    color: bool,
    paper_size: str = None,
) -> str:
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = (
        f"Print Job {'Color' if color else 'BW'}{f' {paper_size}' if paper_size else ''}"
    )

    with open(file_path, "rb") as f:
        attachment = MIMEApplication(
            f.read(),
            _subtype="pdf" if file_extension in [".pdf", ".doc", ".docx"] else "jpg",
        )
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=(
                "file.pdf"
                if file_extension in [".pdf", ".doc", ".docx"]
                else "file.jpg"
            ),
        )
        msg.attach(attachment)

    try:
        with smtplib.SMTP("smtp.yandex.ru", 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        if to_email == EMAIL_TO:
            redis_client.set("print_job", "1")
            redis_client.set("print_color", "1" if color else "0")
            redis_client.set(
                "print_paper_size", paper_size if paper_size else "A4"
            )  # По умолчанию A4
        return f"Отправлено на {to_email} ({'цвет' if color else 'ч/б'}{f', {paper_size}' if paper_size else ''})!"
    except Exception as e:
        return f"Ошибка отправки: {e}"


async def handle_file(
    message: types.Message, target: str, color: bool, paper_size: str = None
):
    file_id = (
        message.document.file_id if message.document else message.photo[-1].file_id
    )
    file = await bot.get_file(file_id)
    file_path = file.file_path
    downloaded_file = await bot.download_file(file_path)

    file_extension = (
        os.path.splitext(file.file_name)[1].lower()
        if message.document and file.file_name
        else ".jpg"
    )
    if file_extension not in [".pdf", ".jpg", ".doc", ".docx"]:
        await message.reply(
            "Формат не поддерживается! Используйте .pdf, .jpg, .doc или .docx."
        )
        return

    local_file = f"/tmp/file{file_extension}"
    with open(local_file, "wb") as f:
        f.write(downloaded_file.read())

    try:
        final_file = await convert_to_pdf(local_file, file_extension)
    except Exception as e:
        os.remove(local_file)
        await message.reply(str(e))
        return

    if target == "kyocera":
        result = await print_to_kyocera(final_file, color, paper_size)
    elif target == "hp":
        result = await send_to_email(HP_EMAIL, final_file, file_extension, color)
    elif target == "kyocera_email":
        result = await send_to_email(
            EMAIL_TO, final_file, file_extension, color, paper_size
        )

    if final_file != local_file:
        os.remove(final_file)
    if os.path.exists(local_file):
        os.remove(local_file)
    await message.reply(result)


# Kyocera команды
@dp.message(Command("kyocera_color_a3"))
async def print_kyocera_color_a3(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera", True, "A3")


@dp.message(Command("kyocera_color_a4"))
async def print_kyocera_color_a4(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera", True, "A4")


@dp.message(Command("kyocera_bw_a3"))
async def print_kyocera_bw_a3(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera", False, "A3")


@dp.message(Command("kyocera_bw_a4"))
async def print_kyocera_bw_a4(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera", False, "A4")


# HP команды
@dp.message(Command("hp_color"))
async def print_hp_color(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "hp", True)


@dp.message(Command("hp_bw"))
async def print_hp_bw(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "hp", False)


# Kyocera через email команды
@dp.message(Command("kyocera_email_color_a3"))
async def print_kyocera_email_color_a3(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera_email", True, "A3")


@dp.message(Command("kyocera_email_color_a4"))
async def print_kyocera_email_color_a4(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera_email", True, "A4")


@dp.message(Command("kyocera_email_bw_a3"))
async def print_kyocera_email_bw_a3(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera_email", False, "A3")


@dp.message(Command("kyocera_email_bw_a4"))
async def print_kyocera_email_bw_a4(message: types.Message):
    if not message.reply_to_message or not (
        message.reply_to_message.document or message.reply_to_message.photo
    ):
        await message.reply("Ответь на сообщение с файлом!")
        return
    await handle_file(message.reply_to_message, "kyocera_email", False, "A4")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
