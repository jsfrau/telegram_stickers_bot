# main.py

import logging
import traceback

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler
)

# main.py

# main.py

from handlers import (
    handle_photo_edit,
    handle_new_photo,
    handle_edit_options,
    handle_skip_all,
    handle_privacy_selection,
    create_new_pack,
    handle_pack_name,
    handle_mode_selection,
    prepare_stickers_for_pack,
    handle_emoji,
    handle_skip,
    edit_pack,
    edit_pack_details,
    handle_edit_pack_name,
    process_new_pack_name,
    delete_pack,
    confirm_delete_pack,
    start,
    button_callback,
    view_public_packs,
    admin_panel,
    admin_panel_buttons,
    admin_users,
    admin_users_pagination,
    admin_user_packs,
    admin_pack_actions,
    admin_delete_pack,
    admin_all_packs,
    admin_all_packs_pagination,
    admin_all_pack_actions,
    admin_all_delete_pack,
    process_media  # Добавлено
)
from handlers.create import handle_video_validation, handle_media_processing, process_media, handle_sticker_edit, \
    handle_new_sticker, handle_image_selection, initiate_image_selection, present_image_selection, \
    create_pack_with_selected_images, handle_process_images_button, handle_variant_selection, handle_media_navigation

from states import (
    CHOOSING_ACTION,
    AWAITING_PACK_NAME,
    AWAITING_PRIVACY,
    #VARIANT_SELECTION,
    PROCESSING_STICKERS,
    AWAITING_EMOJI,
    EDITING_PHOTOS,
    ADMIN_PANEL,
    ADMIN_USER_LIST,
    ADMIN_PACK_LIST,
    ADMIN_PACK_ACTION,
    ADMIN_ALL_PACKS,
    ADMIN_ALL_PACK_ACTION,
    VIDEO_VALIDATION, PROCESSING_MEDIA, EDITING_STICKERS, AWAITING_IMAGE_SELECTION
)

from database import initialize_db, add_user_message, get_public_packs
from utils import cleanup_temp_files, log_error
import config

# Определяем глобальный обработчик ошибок
async def global_error_handler(update, context):
    """Глобальный обработчик ошибок."""
    try:
        raise context.error
    except Exception as e:
        error_message = f"Произошла ошибка: {str(e)}"
        user_id = None
        if update and update.effective_user:
            user_id = update.effective_user.id
        log_file = log_error(error_message, traceback.format_exc(), user_id=user_id)
        logging.error(f"Ошибка: {str(e)}", exc_info=True)
        if update and update.effective_message:
            await update.effective_message.reply_text('Произошла ошибка. Пожалуйста, попробуйте позже.')
        if update and update.effective_message:
            message_text = update.effective_message.text or update.effective_message.caption
            if user_id:
                add_user_message(user_id, message_text, has_error=True, error_log_link=log_file)

def main() -> None:
    # Включаем логирование
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    initialize_db()
    try:
        initialize_db()
        application = ApplicationBuilder().token(config.TOKEN).build()

        # Конфигурируем ConversationHandler для создания стикерпаков
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                CHOOSING_ACTION: [
                    CallbackQueryHandler(button_callback,
                                         pattern='^(about|create_new|edit_pack|delete_pack|admin_panel|view_public_packs)$'),
                ],
                PROCESSING_STICKERS: [
                    MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, process_media),
                    CallbackQueryHandler(handle_mode_selection,
                                         pattern='^(continue|create_pack|edit_stickers|process_media|cancel)$'),
                ],
                EDITING_PHOTOS: [
                    CallbackQueryHandler(edit_pack_details, pattern=r'^edit_\d+$'),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_photo_edit),
                    MessageHandler(filters.PHOTO, handle_new_photo),
                    CallbackQueryHandler(handle_edit_options, pattern='^(edit_more|edit_done)$'),
                    CallbackQueryHandler(handle_edit_pack_name, pattern='^edit_pack_name$'),
                ],
                EDITING_STICKERS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sticker_edit),
                    MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_new_sticker),
                    CallbackQueryHandler(handle_edit_options, pattern='^(edit_more|edit_done)$'),
                ],
                AWAITING_EMOJI: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emoji),
                    CallbackQueryHandler(handle_skip, pattern='^skip$'),
                    CallbackQueryHandler(handle_skip_all, pattern='^skip_all$'),
                ],
                AWAITING_PACK_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_name),
                    CommandHandler("back", handle_edit_pack_name)
                ],
                AWAITING_PRIVACY: [
                    CallbackQueryHandler(handle_privacy_selection, pattern='^(private|public|back_to_main)$'),
                ],
                ADMIN_PANEL: [
                    CallbackQueryHandler(admin_panel_buttons,
                                         pattern='^(admin_users|admin_all_packs|admin_access_pack|back_to_main)$'),
                ],
                ADMIN_USER_LIST: [
                    CallbackQueryHandler(admin_users_pagination, pattern='^(admin_users_next|admin_users_prev)$'),
                    CallbackQueryHandler(admin_user_packs, pattern=r'^admin_user_\d+$'),
                    CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
                ],
                ADMIN_PACK_LIST: [
                    CallbackQueryHandler(admin_pack_actions, pattern=r'^admin_pack_\d+$'),
                    CallbackQueryHandler(admin_users, pattern='^admin_users$'),
                ],
                ADMIN_PACK_ACTION: [
                    CallbackQueryHandler(admin_delete_pack, pattern='^admin_delete_pack$'),
                    CallbackQueryHandler(admin_user_packs, pattern=r'^admin_user_\d+$'),
                ],
                ADMIN_ALL_PACKS: [
                    CallbackQueryHandler(admin_all_packs_pagination,
                                         pattern='^(admin_all_packs_next|admin_all_packs_prev)$'),
                    CallbackQueryHandler(admin_all_pack_actions, pattern=r'^admin_all_pack_\d+$'),
                    CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
                ],
                ADMIN_ALL_PACK_ACTION: [
                    CallbackQueryHandler(admin_all_delete_pack, pattern='^admin_all_delete_pack$'),
                    CallbackQueryHandler(admin_all_packs, pattern='^admin_all_packs$'),
                ],
                VIDEO_VALIDATION: [
                    CallbackQueryHandler(handle_video_validation,
                                         pattern='^(trim_current_video|trim_all_videos|delete_current_video|prev_invalid_video|next_invalid_video|back_to_previous_menu)$'),
                ],
                PROCESSING_MEDIA: [
                    CallbackQueryHandler(handle_media_navigation,
                                         pattern='^(prev_media|next_media|back_to_previous_menu|process_current_media)$'),
                    CallbackQueryHandler(handle_variant_selection, pattern='^select_variant_\d+$'),
                    CallbackQueryHandler(create_pack_with_selected_images, pattern='^create_pack$'),
                    #CallbackQueryHandler(continue_processing, pattern='^continue_processing$'),
                    # ... другие обработчики
                ],
                AWAITING_IMAGE_SELECTION: [
                    CallbackQueryHandler(handle_image_selection, pattern='^select_image_\d+_(briaai|rembg|u2net)$')
                ],
            },
            fallbacks=[CommandHandler("start", start)],
        )

        application.add_handler(conv_handler)

        # Добавляем глобальный обработчик ошибок
        application.add_error_handler(global_error_handler)

        application.run_polling()
    finally:
        cleanup_temp_files()

if __name__ == '__main__':
    main()
