from imapclient import IMAPClient
import email
import os
import subprocess
import redis
import time

EMAIL = "parta-co-working@yandex.ru"
PASSWORD = "anbrpylhoqyjegdr"
IMAP_SERVER = "imap.yandex.ru"
PRINTER_NAME = "Kyocera2554"
REDIS_HOST = "redis"
REDIS_PORT = 6379

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def convert_to_pdf(file_path: str, original_extension: str) -> str:
    if original_extension in [".doc", ".docx"]:
        output_file = file_path.replace(original_extension, ".pdf")
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
    return file_path


def check_email_and_print():
    color = redis_client.get("print_color") == "1"
    paper_size = redis_client.get("print_paper_size") or "A4"  # По умолчанию A4
    color_option = "RGB" if color else "Grayscale"

    with IMAPClient(IMAP_SERVER) as mail:
        mail.login(EMAIL, PASSWORD)
        mail.select_folder("INBOX")

        messages = mail.search(["UNSEEN"])
        for uid, message_data in mail.fetch(messages, "RFC822").items():
            msg = email.message_from_bytes(message_data[b"RFC822"])

            for part in msg.walk():
                if (
                    part.get_content_maintype() == "application"
                    or part.get_content_type() in ["image/jpeg", "image/png"]
                ):
                    filename = part.get_filename() or "file.pdf"
                    file_extension = os.path.splitext(filename)[1].lower()
                    if file_extension not in [".pdf", ".jpg", ".doc", ".docx"]:
                        continue
                    with open(filename, "wb") as f:
                        f.write(part.get_payload(decode=True))

                    final_file = convert_to_pdf(filename, file_extension)
                    subprocess.run(
                        [
                            "lp",
                            "-h",
                            "host.docker.internal:631",
                            "-d",
                            PRINTER_NAME,
                            "-o",
                            "fit-to-page",
                            "-o",
                            f"ColorModel={color_option}",
                            "-o",
                            f"media={paper_size}",
                            final_file,
                        ]
                    )
                    os.remove(final_file)
            mail.add_flags([uid], ["\\Seen"])


while True:
    if redis_client.get("print_job") == "1":
        try:
            check_email_and_print()
            redis_client.set("print_job", "0")
            redis_client.delete("print_color")
            redis_client.delete("print_paper_size")
        except Exception as e:
            print(f"Ошибка: {e}")
    time.sleep(5)
