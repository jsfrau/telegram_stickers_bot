# handlers/__init__.py

from .create import (
    create_new_pack,
    handle_pack_name,
    process_media,
    handle_mode_selection,
    prepare_stickers_for_pack,
    handle_emoji,
    handle_skip,
    handle_skip_all,
    edit_photos,
    edit_stickers,
    handle_sticker_edit,
    handle_new_sticker,
    handle_new_photo,
    handle_edit_options,
    handle_privacy_selection
)

from .edit import (
    edit_pack,
    edit_pack_details,
    handle_edit_pack_name,
    process_new_pack_name,
    handle_photo_edit  # Добавляем импорт здесь
)

from .delete import delete_pack, confirm_delete_pack

from .start import start, button_callback, view_public_packs

from .admin import (
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
    admin_all_delete_pack
)

__all__ = [
    'start',
    'button_callback',
    'create_new_pack',
    'handle_pack_name',
    'process_media',
    'handle_mode_selection',
    'prepare_stickers_for_pack',
    'handle_emoji',
    'handle_skip',
    'handle_skip_all',
    'edit_photos',
    'edit_stickers',
    'handle_sticker_edit',
    'handle_new_sticker',
    'handle_new_photo',
    'handle_edit_options',
    'handle_privacy_selection',
    'edit_pack',
    'edit_pack_details',
    'handle_edit_pack_name',
    'process_new_pack_name',
    'handle_photo_edit',  # Перемещаем в правильное место
    'delete_pack',
    'confirm_delete_pack',
    'view_public_packs',
    'admin_panel',
    'admin_panel_buttons',
    'admin_users',
    'admin_users_pagination',
    'admin_user_packs',
    'admin_pack_actions',
    'admin_delete_pack',
    'admin_all_packs',
    'admin_all_packs_pagination',
    'admin_all_pack_actions',
    'admin_all_delete_pack'
]
