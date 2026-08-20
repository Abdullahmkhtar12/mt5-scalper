from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Settings
from trading_engine import TradingEngine

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, settings: Settings, engine: TradingEngine):
        self.settings = settings
        self.engine = engine

    def authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and int(chat.id) == self.settings.telegram_chat_id

    async def reject_unauthorized(self, update: Update) -> None:
        if update.effective_message:
            await update.effective_message.reply_text("غير مصرح بهذا الحساب.")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        await update.effective_message.reply_text(
            "تم الاتصال بالبوت. الأوامر المتاحة: /status /stop /resume /closeall /set_spread <points>"
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        try:
            await update.effective_message.reply_text(await self.engine.status_text())
        except Exception as exc:
            logger.exception("Status command failed")
            await update.effective_message.reply_text(f"تعذر جلب الحالة: {exc}")

    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        await self.engine.pause()
        await update.effective_message.reply_text("تم إيقاف إشارات الدخول الجديدة. ستستمر إدارة الصفقات المفتوحة.")

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        await self.engine.resume()
        await update.effective_message.reply_text("تم استئناف إشارات الدخول الجديدة.")

    async def close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        try:
            result = await self.engine.close_all()
            await update.effective_message.reply_text(result)
        except Exception as exc:
            logger.exception("Close-all command failed")
            await update.effective_message.reply_text(f"تعذر تنفيذ الإغلاق: {exc}")

    async def set_spread(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await self.reject_unauthorized(update)
            return
        if not context.args:
            await update.effective_message.reply_text("الاستخدام: /set_spread <points>")
            return
        try:
            value = int(context.args[0])
            await self.engine.set_spread(value)
            await update.effective_message.reply_text(f"تم تحديث الحد الأقصى للسبريد إلى {value} نقطة.")
        except (ValueError, TypeError) as exc:
            await update.effective_message.reply_text(f"قيمة غير صالحة: {exc}")

    async def error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Telegram update error: %s", context.error)

    async def notify(self, text: str) -> None:
        application = ApplicationBuilderProxy.current
        if application is None:
            logger.warning("Telegram application is not ready")
            return
        await application.bot.send_message(chat_id=self.settings.telegram_chat_id, text=text)


class ApplicationBuilderProxy:
    current: Application | None = None


def build_application(settings: Settings, engine: TradingEngine) -> Application:
    controller = TelegramController(settings, engine)
    application = Application.builder().token(settings.telegram_bot_token).build()
    ApplicationBuilderProxy.current = application

    application.add_handler(CommandHandler("start", controller.start))
    application.add_handler(CommandHandler("status", controller.status))
    application.add_handler(CommandHandler("stop", controller.stop))
    application.add_handler(CommandHandler("resume", controller.resume))
    application.add_handler(CommandHandler("closeall", controller.close_all))
    application.add_handler(CommandHandler("set_spread", controller.set_spread))
    application.add_error_handler(controller.error)
    engine.notifier = controller.notify
    return application
