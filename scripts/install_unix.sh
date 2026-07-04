#!/usr/bin/env bash
# macOS / Linux installer: venv + deps + launcher.
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

cat > run.sh <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
.venv/bin/python -m app.main
EOF
chmod +x run.sh

# Linux desktop entry
if [ -d "$HOME/.local/share/applications" ]; then
  cat > "$HOME/.local/share/applications/phd-supervisor-finder.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PhD Supervisor Finder
Exec=$(pwd)/run.sh
Terminal=false
Categories=Education;
EOF
  echo "Desktop entry created (Linux)."
fi
echo "Done. Launch with ./run.sh (macOS: you can also make an Automator app that runs run.sh)."
