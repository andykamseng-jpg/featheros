"""Simple interactive cloud connection. Credentials remain in this process only."""
import getpass
import os
import sys
from urllib.parse import urlparse
from .server import main


def connect():
    print('Connect Feather to your existing cloud AI service.')
    print('Use a model with function calling and a chat-completions-compatible endpoint.')
    endpoint = input('Full HTTPS endpoint: ').strip()
    if urlparse(endpoint).scheme != 'https':
        raise SystemExit('Enter an HTTPS endpoint.')
    model = input('Model name: ').strip()
    key = getpass.getpass('Provider API key (hidden): ').strip()
    if not model or not key:
        raise SystemExit('A model and provider key are required.')
    os.environ.update(FEATHER_AI_URL=endpoint, FEATHER_AI_MODEL=model, FEATHER_AI_KEY=key)
    print('Key kept in process memory. Nothing is saved to the source code.')
    # Preserve launch flags such as --enable-commands and --data-dir.
    main()


if __name__ == '__main__':
    connect()
