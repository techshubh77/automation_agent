import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config.settings import settings
from app.utils.logger import logger


def _send_smtp_email_sync(subject: str, html_content: str, to_email: str):
    """Synchronous SMTP sender execution block."""
    if not settings.mail_username or not settings.mail_password:
        logger.warning(
            "[Email Helper] Mail credentials missing. Skipping email dispatch."
        )
        return

    if not to_email:
        logger.warning(
            "[Email Helper] Destination email missing. Skipping email dispatch."
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.mail_from_email
    msg["To"] = to_email

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(settings.mail_host, settings.mail_port) as server:
            server.starttls()
            server.login(settings.mail_username, settings.mail_password)
            server.sendmail(settings.mail_from_email, to_email, msg.as_string())
            logger.info(
                f"[Email Helper] Successfully connected and sent email via {settings.mail_host}"
            )
    except Exception as e:
        logger.error(f"[Email Helper] SMTP connection failed: {e!s}")
        raise e


async def send_ingestion_alert(
    doc_id: str,
    filename: str,
    status: str,
    to_email: str,
    error_message: str | None = None,
):
    """Asynchronous wrapper that offloads the SMTP connection to a worker thread."""
    subject = f"Ingestion Job {status.upper()}: {filename}"

    # Base styling
    color = "#10B981" if status == "completed" else "#EF4444"
    icon = "✅" if status == "completed" else "❌"
    status_text = "Successfully Completed" if status == "completed" else "Failed"

    error_block = (
        f"""
    <div style="margin-top: 20px; padding: 15px; background-color: #FEF2F2; border-left: 4px solid #EF4444; border-radius: 4px;">
        <h4 style="margin: 0 0 10px 0; color: #991B1B; font-size: 14px;">Error Details</h4>
        <pre style="margin: 0; color: #7F1D1D; font-family: ui-monospace, monospace; font-size: 13px; white-space: pre-wrap;">{error_message}</pre>
    </div>
    """
        if status != "completed" and error_message
        else ""
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F3F4F6; padding: 40px 20px;">
            <tr>
                <td align="center">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #FFFFFF; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); overflow: hidden;">
                        <!-- Header -->
                        <tr>
                            <td style="background-color: {color}; padding: 30px 40px; text-align: center;">
                                <h1 style="margin: 0; color: #FFFFFF; font-size: 24px; font-weight: 600; letter-spacing: -0.5px;">{icon} Ingestion {status_text}</h1>
                            </td>
                        </tr>

                        <!-- Body -->
                        <tr>
                            <td style="padding: 40px;">
                                <p style="margin: 0 0 20px 0; color: #374151; font-size: 16px; line-height: 24px;">
                                    The document ingestion process has finished executing. Here are the details of the job:
                                </p>

                                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F9FAFB; border-radius: 6px; border: 1px solid #E5E7EB;">
                                    <tr>
                                        <td style="padding: 15px 20px; border-bottom: 1px solid #E5E7EB;">
                                            <span style="display: block; color: #6B7280; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">File Name</span>
                                            <span style="color: #111827; font-size: 15px; font-weight: 500;">{filename}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 15px 20px;">
                                            <span style="display: block; color: #6B7280; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Document ID</span>
                                            <span style="color: #111827; font-size: 14px; font-family: ui-monospace, monospace;">{doc_id}</span>
                                        </td>
                                    </tr>
                                </table>

                                {error_block}

                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td style="padding: 24px 40px; background-color: #F9FAFB; border-top: 1px solid #E5E7EB; text-align: center;">
                                <p style="margin: 0; color: #6B7280; font-size: 13px;">
                                    This is an automated message from the <strong>Automation Agent</strong> system.<br>
                                    Please do not reply directly to this email.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    try:
        # Offload blocking SMTP call to a separate execution thread
        await asyncio.to_thread(_send_smtp_email_sync, subject, html, to_email)
        logger.info(
            f"[Email Helper] Email notification sent for Document: {doc_id} with status: {status}"
        )
    except Exception as e:
        logger.error(
            f"[Email Helper] Failed to send email alert for Document {doc_id}: {e!s}"
        )
