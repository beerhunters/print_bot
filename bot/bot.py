import asyncio
import os
import subprocess
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/tmp/bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Конфигурация через переменные окружения
API_TOKEN = os.getenv("API_TOKEN")
PRINTER_NAME = os.getenv("PRINTER_NAME", "HP_M479")  # Имя принтера в CUPS

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# Определение состояний
class PrintStates(StatesGroup):
    waiting_for_file_color = State()
    waiting_for_file_bw = State()


@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я помогу напечатать документы на HP.\n"
        "Команды:\n"
        "/hp_color - цветная печать\n"
        "/hp_bw - ч/б печать\n"
        "После команды отправь файл (.pdf, .jpg, .doc, .docx)."
    )


@dp.message(Command("hp_color"))
async def start_color_printing(message: types.Message, state: FSMContext):
    await message.reply("Отправь мне файл для цветной печати на HP.")
    await state.set_state(PrintStates.waiting_for_file_color)
    logger.info(f"User {message.from_user.id} started color printing")


@dp.message(Command("hp_bw"))
async def start_bw_printing(message: types.Message, state: FSMContext):
    await message.reply("Отправь мне файл для ч/б печати на HP.")
    await state.set_state(PrintStates.waiting_for_file_bw)
    logger.info(f"User {message.from_user.id} started BW printing")


async def convert_to_pdf(file_path: str, original_extension: str) -> str:
    logger.info(f"Converting file {file_path} with extension {original_extension}")
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
            logger.info(f"Converted to {output_file}")
            return f"/tmp/{os.path.basename(output_file)}"
        except subprocess.CalledProcessError as e:
            logger.error(f"Conversion error: {e}")
            raise Exception(f"Ошибка конвертации: {e}")
    return file_path


async def print_to_hp(file_path: str, color: bool) -> str:
    """Печатает файл через CUPS."""
    color_option = "RGB" if color else "Grayscale"
    try:
        subprocess.run(
            [
                "lp",
                "-d",
                PRINTER_NAME,
                "-o",
                "fit-to-page",
                "-o",
                f"ColorModel={color_option}",
                "-o",
                "media=A4",  # HP M479 поддерживает только A4
                file_path,
            ],
            check=True,
            timeout=60,
        )
        logger.info(f"Print job sent to {PRINTER_NAME} (color: {color})")
        return f"Напечатано на HP ({'цвет' if color else 'ч/б'})!"
    except subprocess.CalledProcessError as e:
        logger.error(f"Print error: {e}")
        return f"Ошибка печати: {e}"


async def handle_file(message: types.Message, state: FSMContext, color: bool):
    user_id = message.from_user.id
    logger.info(f"Handling file from user {user_id}")

    if not (message.document or message.photo):
        await message.reply("Пожалуйста, отправь файл (.pdf, .jpg, .doc, .docx)!")
        logger.warning(f"User {user_id} sent non-file message")
        return

    file_id = (
        message.document.file_id if message.document else message.photo[-1].file_id
    )
    file = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file.file_path)

    file_extension = (
        os.path.splitext(message.document.file_name)[1].lower()
        if message.document
        else ".jpg"
    )
    logger.info(f"File extension: {file_extension}")

    if file_extension not in [".pdf", ".jpg", ".doc", ".docx"]:
        await message.reply(
            "Формат не поддерживается! Используй .pdf, .jpg, .doc или .docx."
        )
        logger.warning(f"Unsupported file format: {file_extension}")
        await state.clear()
        return

    local_file = f"/tmp/file{file_extension}"
    with open(local_file, "wb") as f:
        f.write(downloaded_file.read())
    logger.info(f"File saved locally: {local_file}")

    try:
        final_file = await convert_to_pdf(local_file, file_extension)
        result = await print_to_hp(final_file, color)
    except Exception as e:
        if os.path.exists(local_file):
            os.remove(local_file)
        logger.error(f"Processing error: {e}")
        await message.reply(str(e))
        await state.clear()
        return

    if os.path.exists(final_file) and final_file != local_file:
        os.remove(final_file)
    if os.path.exists(local_file):
        os.remove(local_file)
    logger.info(f"File processed and cleaned up: {final_file}")

    await message.reply(result)
    await state.clear()


@dp.message(PrintStates.waiting_for_file_color)
async def process_file_color(message: types.Message, state: FSMContext):
    await handle_file(message, state, color=True)


@dp.message(PrintStates.waiting_for_file_bw)
async def process_file_bw(message: types.Message, state: FSMContext):
    await handle_file(message, state, color=False)


async def main():
    logger.info("Starting bot")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
