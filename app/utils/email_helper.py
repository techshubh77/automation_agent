import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config.settings import settings
from app.utils.logger import logger

def _send_smtp_email_sync(subject: str, html_content: str):
    """Synchronous SMTP sender execution block."""
    if not settings.mail_username or not settings.mail_password:
        logger.warning("[Email Helper] Mail credentials missing. Skipping email dispatch.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.mail_from_email
    msg["To"] = settings.mail_to_email

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.mail_host, settings.mail_port) as server:
            server.starttls()
            server.login(settings.mail_username, settings.mail_password)
            server.sendmail(settings.mail_from_email, settings.mail_to_email, msg.as_string())
            logger.info(f"[Email Helper] Successfully connected and sent email via {settings.mail_host}")
    except Exception as e:
        logger.error(f"[Email Helper] SMTP connection failed: {e!s}")
        raise e

async def send_ingestion_alert(doc_id: str, filename: str, status: str, error_message: str | None = None):
    """Asynchronous wrapper that offloads the SMTP connection to a worker thread."""
    subject = f"Ingestion Job {status.upper()}: {filename}"
    
    if status == "completed":
        html = f"""
        <h3>Ingestion Job Succeeded</h3>
        <p><b>Document ID:</b> {doc_id}</p>
        <p><b>File Name:</b> {filename}</p>
        <p>Status is now marked as <b>completed</b> in the database.</p>
        """
    else:
        html = f"""
        <h3>Ingestion Job Failed</h3>
        <p><b>Document ID:</b> {doc_id}</p>
        <p><b>File Name:</b> {filename}</p>
        <p><b>Error Details:</b> <pre style="color: red;">{error_message}</pre></p>
        <p>Status is marked as <b>failed</b> in the database.</p>
        """

    try:
        # Offload blocking SMTP call to a separate execution thread
        await asyncio.to_thread(_send_smtp_email_sync, subject, html)
        logger.info(f"[Email Helper] Email notification sent for Document: {doc_id} with status: {status}")
    except Exception as e:
        logger.error(f"[Email Helper] Failed to send email alert for Document {doc_id}: {e!s}")
