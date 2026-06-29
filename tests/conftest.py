import os

import pygame


def pytest_configure() -> None:
    """Configure pygame for headless CI before any test runs."""
    os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    pygame.display.init()
    pygame.font.init()
