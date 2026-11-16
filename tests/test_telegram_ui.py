from news_digest.telegram_ui import main_keyboard


def test_main_menu_uses_button_navigation():
    keyboard = main_keyboard()
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }
    assert "ui:projects" in callbacks
    assert "ui:create" in callbacks
    assert "ui:help" in callbacks


def test_main_menu_does_not_expose_manual_subcommands():
    keyboard = main_keyboard()
    labels = [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert all("/news" not in label for label in labels)
    assert all("slug" not in label.lower() for label in labels)
