import asyncio
import os
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# Конфигурация через переменные окружения
API_TOKEN = os.getenv("API_TOKEN")
HP_EMAIL = os.getenv("HP_EMAIL")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# Определение состояний
class PrintStates(StatesGroup):
    waiting_for_file_color = State()  # Ожидание файла для цветной печати
    waiting_for_file_bw = State()  # Ожидание файла для ч/б печати


@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я помогу напечатать документы на HP.\n"
        "Команды:\n"
        "/hp_color - цветная печать\n"
        "/hp_bw - ч/б печать\n"
        "После команды просто отправь мне файл (.pdf, .jpg, .doc, .docx)."
    )


@dp.message(Command("hp_color"))
async def start_color_printing(message: types.Message, state: FSMContext):
    await message.reply("Отправь мне файл для цветной печати на HP.")
    await state.set_state(PrintStates.waiting_for_file_color)


@dp.message(Command("hp_bw"))
async def start_bw_printing(message: types.Message, state: FSMContext):
    await message.reply("Отправь мне файл для ч/б печати на HP.")
    await state.set_state(PrintStates.waiting_for_file_bw)


async def convert_to_pdf(file_path: str, original_extension: str) -> str:
    """Конвертирует .doc/.docx в PDF, если нужно."""
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
            if os.path.exists(file_path):
                os.remove(file_path)
            return f"/tmp/{os.path.basename(output_file)}"
        except subprocess.CalledProcessError as e:
            raise Exception(f"Ошибка конвертации: {e}")
    return file_path


async def send_to_hp_email(file_path: str, file_extension: str, color: bool) -> str:
    """Отправляет файл на email HP для печати."""
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = HP_EMAIL
    msg["Subject"] = f"Print Job {'Color' if color else 'BW'}"

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
        with smtplib.SMTP("smtp.yandex.ru", 587, timeout=30) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        return f"Отправлено на HP ({'цвет' if color else 'ч/б'})!"
    except Exception as e:
        return f"Ошибка отправки: {e}"


async def handle_file(message: types.Message, state: FSMContext, color: bool):
    """Обрабатывает полученный файл."""
    if not (message.document or message.photo):
        await message.reply("Пожалуйста, отправь файл (.pdf, .jpg, .doc, .docx)!")
        return

    file_id = (
        message.document.file_id if message.document else message.photo[-1].file_id
    )
    file = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file.file_path)

    # Получаем расширение файла
    file_extension = (
        os.path.splitext(message.document.file_name)[1].lower()
        if message.document
        else ".jpg"
    )
    if file_extension not in [".pdf", ".jpg", ".doc", ".docx"]:
        await message.reply(
            "Формат не поддерживается! Используй .pdf, .jpg, .doc или .docx."
        )
        await state.clear()
        return

    local_file = f"/tmp/file{file_extension}"
    with open(local_file, "wb") as f:
        f.write(downloaded_file.read())

    try:
        final_file = await convert_to_pdf(local_file, file_extension)
        result = await send_to_hp_email(final_file, file_extension, color)
    except Exception as e:
        if os.path.exists(local_file):
            os.remove(local_file)
        await message.reply(str(e))
        await state.clear()
        return

    if os.path.exists(final_file) and final_file != local_file:
        os.remove(final_file)
    if os.path.exists(local_file):
        os.remove(local_file)

    await message.reply(result)
    await state.clear()


@dp.message(PrintStates.waiting_for_file_color)
async def process_file_color(message: types.Message, state: FSMContext):
    await handle_file(message, state, color=True)


@dp.message(PrintStates.waiting_for_file_bw)
async def process_file_bw(message: types.Message, state: FSMContext):
    await handle_file(message, state, color=False)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
