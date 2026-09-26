# leefanniv

Team scoring across games during a party. Django + SQLite, served by gunicorn
under a systemd user unit, reached over WireGuard.

## Dev

    pixi run migrate && pixi run runserver
    pixi run -e dev all        # fmt, lint, type-check, test

## Server

    git clone <repo> ~/leefanniv && cd ~/leefanniv && pixi install
    mkdir -p ~/.config/leefanniv ~/.local/share/leefanniv
    cp deploy/leefanniv.env.example ~/.config/leefanniv/server.env  # then edit
    chmod 600 ~/.config/leefanniv/server.env
    cp deploy/leefanniv.service ~/.config/systemd/user/
    systemctl --user daemon-reload && systemctl --user enable --now leefanniv
    sudo loginctl enable-linger $USER

Then open `http://10.8.0.1:8003` from the phone. Corrections (rename, delete
a player or game) go through `/admin/` after `pixi run manage createsuperuser`.
