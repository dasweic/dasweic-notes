Dasweic Notes
A local-first desktop notes and canvas application with a minimal black interface, encrypted project files, and encrypted persistent attachment storage. The application is built with Python and PySide6 and is intended for Linux and Windows desktops.
Features
- Canvas workspace: arrange notes and imported attachments on a canvas.
- Text notes and text previews: create and work with text content inside the application.
- Attachment viewing: open supported image, text, PDF, audio, and video files where the installed Qt modules and system codecs support them.
- Video playback: play/pause, stop, seek, volume/mute, playback speed, and fullscreen controls when Qt Multimedia is available.
- Fullscreen modes: use the relevant fullscreen button or keyboard shortcut shown by the viewer; Esc exits fullscreen where supported.
- Capture/recording tools: camera, microphone, and other capture options depend on available devices and the installed Qt Multimedia backend.
- Encrypted .dasweic projects: project files are protected with a password.
- Encrypted attachment vault: imported attachments are stored under data/attachments/ beside main.py as encrypted .denc files.
- Dark interface: black/dark styling with neutral text and controls.
- Offline-first: no account or network service is required for the basic local workflow.
Playback, recording, PDF viewing, and image-format support can vary by operating system, Qt modules, multimedia backend, codecs, and device availability.

Requirements
- Python 3.10 or newer (Python 3.11 or 3.12 is a practical choice for broad package compatibility).
- PySide6 6.7 or newer, below version 7.
- cryptography 42.0 or newer.
- PyMuPDF 1.24 or newer for the fallback PDF renderer.
- For audio/video playback and recording: a working Qt Multimedia backend, system codecs, and the relevant hardware permissions/devices.
Installation
Run these commands from the directory containing main.py, requirements.txt, and this README.
Linux (Ubuntu/Debian) or Windows
Create a virtual environment:
python3 -m venv .venv
source .venv/bin/activate
On Windows PowerShell, activate it with:
py -m venv .venv
.\.venv\Scripts\Activate.ps1
Install dependencies:
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Start the application:
python main.py
On Linux, if python3 points to an older or unavailable Python version, install a supported Python version and its venv package using your distribution's package manager first.
First launch and password
On first launch, the application initializes its local authentication settings. In the current source, the initial password is djsar. After unlocking, use the application's password-change option to replace it with a strong, unique password. Do not leave the initial password in place for private data.

The password verifier is stored in the user's home configuration directory, separate from the project files. Keep your password safe: encrypted data may be unrecoverable if the required password is lost.
Data locations
- Projects: saved wherever you choose to save each .dasweic project.
- Encrypted attachment vault: <directory-containing-main.py>/data/attachments/.
- Application settings/authentication metadata: ~/.dasweic_notes/ on Linux and other systems where Path.home() resolves to the user's home directory.
- Temporary working files: attachment previews and playback may use temporary decrypted copies while the application is running. The application attempts to keep these within its private session temporary directory and cleans up session files on exit, but this is not equivalent to keeping plaintext out of memory or guaranteeing secure deletion on every filesystem.
Back up both your .dasweic project files and the data/ directory. The project contains the canvas/layout state; the attachment vault holds persistent encrypted copies of imported files. Keep backups protected and test that you can open them before deleting originals.
Video playback notes
The player uses Qt Multimedia. Supported formats depend on the installed Qt Multimedia backend and available system codecs; an extension alone does not guarantee that a particular media file will play.

Basic controls include play/pause, stop, seeking, volume/mute, and playback speed when exposed by the current player UI. Use the fullscreen control or the supported keyboard shortcut to enter fullscreen; press Esc or use the on-screen exit control to leave it. Fullscreen uses the display's available fullscreen size (for example, 1920×1080 on a 1920×1080 display); it does not change the monitor's resolution.

If playback or recording does not work:
1. Update/reinstall the dependencies with python -m pip install --upgrade -r requirements.txt.
2. Confirm that the file plays in another local player and try a common format such as H.264/AAC in MP4.
3. Check the operating system's audio/camera permissions and that the intended devices are available.
4. On Linux, verify that Qt Multimedia's platform backend and the system codecs required by your distribution are installed.
5. Run python main.py from a terminal to see any Qt Multimedia or codec diagnostics.
Security notes
- Use a strong password and keep encrypted project and vault backups.
- The vault's encrypted files are stored in data/attachments/; imported files can be temporarily decrypted for viewing or playback.
- Temporary plaintext, operating-system swap, crash dumps, backups, and filesystem behavior are outside the application's complete control. Treat the computer and backups as part of your security boundary.
- Do not delete the data/ directory if you need its stored attachments.
- This application is not a substitute for a separately audited security product.
Troubleshooting
ModuleNotFoundError: No module named 'PySide6'
Activate the virtual environment and run:
python -m pip install -r requirements.txt
PDF viewer is unavailable
Check that the dependencies installed successfully. The application uses QtPdf when available and PyMuPDF as a fallback renderer.
Video or audio does not play
This is often a backend/codec compatibility issue rather than a missing UI control. Check the terminal output and try a commonly supported media file.
Permission error creating data/attachments/
Ensure the directory containing main.py is writable by your user. The attachment vault is stored next to main.py, so a read-only installation directory will not work for imports that need persistent storage.
Project files
project-folder/
├── main.py
├── requirements.txt
├── README.md
└── data/
    └── attachments/    # created automatically; encrypted .denc files
The data/ directory is created automatically when the application initializes its attachment storage.