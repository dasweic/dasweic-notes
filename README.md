
# ✦ Dasweic Notes

### Your Ideas. Your Canvas. Your Universe.

Dasweic Notes is a desktop note-taking and visual workspace application built with Python and PySide6. It is designed to help you organize ideas, create notes, work with media, and manage documents on a flexible canvas with a premium cosmic-dark interface.

The application is designed for offline use, with locally stored projects and password-protected project encryption.

---

## ✨ Features

### 🎨 1. Cosmic Canvas & Workspace

- Premium dark interface with a cosmic-inspired visual design.
- Large, flexible workspace for organizing ideas and content.
- Multiple independent objects on the canvas.
- Move and arrange canvas objects.
- Zoom in, zoom out, and reset the canvas view.
- Zoom using keyboard shortcuts.
- Touchpad gesture support where supported by the operating system and hardware.
- Navigate and explore your workspace using canvas controls.
- Selection-based object editing.
- Undo and redo support for recorded editing operations.

### 📝 2. Text Notes

- Create text notes directly on the canvas.
- Write multiline text and paragraphs.
- Use text formatting options available in the editor.
- Position notes around your workspace.
- Organize notes alongside images and other content.
- Resize supported text containers using the available resize interaction.
- Edit your workspace without switching between multiple documents.

### 🖼️ 3. Images & Visual Content

- Import local images into your workspace.
- Arrange images alongside notes and other objects.
- Resize supported image objects.
- Keep related visual references together in one project.
- Support for image formats recognized by the installed Qt image plugins, with optional Pillow support for additional formats.

### 🎬 4. Audio & Video

- Work with supported local audio and video files.
- Use available playback controls to preview media within the application.
- Keep media alongside related notes and project material.
- Playback depends on the installed Qt multimedia components, system codecs, and supported media formats.

### 📄 5. Documents & PDF Viewing

- Open supported document attachments.
- View PDF documents when the required PDF components are available.
- Optional PyMuPDF integration provides a PDF rendering fallback.
- Use available PDF viewing options, including color inversion where implemented.
- Keep reference documents connected to your workspace.

PDF and document capabilities depend on the file type and installed optional libraries.

### 📎 6. File Attachments

- Attach local files to your workspace.
- Work with different file types, including documents and media.
- Keep attachments associated with your project.
- Save project content and supported attachments together.
- Export attached files to a selected folder using the Export Files feature.
- Avoid accidental overwriting of existing exported files through unique filenames.

Export behavior depends on the availability of the original attached files and the saved project state.

### 🔐 7. Password Protection & Encryption

- Password-protected access to project operations.
- Password verification when exporting files.
- Encrypted native project files using the application's encryption implementation.
- Password-based key derivation and authenticated encryption.
- Local project storage without requiring a cloud account.
- Protection against opening encrypted projects without the correct password.

**Security note:** Application access protection and project-file encryption are separate concerns. Keep your password safe and maintain backups of important projects.

### 💾 8. Native Project Management

- Save your workspace in the `.dasweic` project format.
- Open previously saved projects.
- Save projects locally.
- Preserve supported project objects and embedded attachment data.
- Continue working on an existing project.
- Export attached files separately when needed.

Always save your work regularly and keep backups of important files.

### ⚡ 9. Keyboard & Navigation

- Keyboard shortcuts for supported editing and navigation actions.
- Canvas zoom controls.
- Selection-based interactions.
- Mouse and supported touchpad interactions.
- Status information for relevant workspace actions.

Some gestures and shortcuts may behave differently depending on the operating system, keyboard layout, touchpad driver, and application version.

---

## 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python 3 | Application logic |
| PySide6 | Desktop GUI and graphics canvas |
| Qt Graphics View | Canvas scene and object rendering |
| cryptography | Encryption and cryptographic operations |
| PyMuPDF | Optional PDF rendering fallback |
| Qt Multimedia | Audio and video playback when available |
| Pillow | Optional additional image format support |

The application is implemented as a single Python source file, `main.py`, with dependencies installed separately.

---

## 📋 Requirements

- Python 3.10 or newer recommended.
- Windows or Linux.
- Sufficient RAM for the size of your project and imported media.
- Sufficient disk space for projects, attachments, and exported files.
- A compatible Qt multimedia environment for audio and video playback.
- Optional PDF and image libraries for additional functionality.

Large projects may require substantial memory and disk space.

---

## 🚀 Installation

### 1. Install Python

Install Python 3.10 or newer from:

https://www.python.org/downloads/

On Linux, Python and pip may also be available through your distribution's package manager.

Verify the installation:

```bash
python --version
```

If your system uses `python3`, run:

```bash
python3 --version
```

### 2. Create the project folder

Keep the application files together in one directory:

```text
Dasweic-Notes/
├── main.py
├── requirements.txt
└── README.md
```

### 3. Install dependencies

If `requirements.txt` is available, run:

**Windows**

```powershell
python -m pip install -r requirements.txt
```

**Linux**

```bash
python3 -m pip install -r requirements.txt
```

Alternatively, install the core dependencies directly:

```bash
python -m pip install PySide6 cryptography PyMuPDF
```

Use `python3` instead of `python` on Linux systems where required.

### 4. Launch the application

**Windows**

```powershell
python main.py
```

**Linux**

```bash
python3 main.py
```

---

## 🖥️ Usage Guide

### Create a workspace

1. Launch Dasweic Notes.
2. Complete the application's password prompt if requested.
3. Use the workspace toolbar and sidebar to access available tools.
4. Add notes, images, documents, or supported media.
5. Arrange objects on the canvas.
6. Save your project in `.dasweic` format.

### Work with text

1. Choose the Add Text action.
2. Enter your text in the editor.
3. Apply the available formatting.
4. Add the note to the canvas.
5. Select and reposition the note as needed.
6. Use the available resize handle where supported.

### Zoom the canvas

Use the application's zoom controls or the supported keyboard shortcuts.

Typical intended shortcuts include:

| Action | Shortcut |
|---|---|
| Zoom in | `Ctrl` + `+` |
| Zoom out | `Ctrl` + `-` |
| Reset zoom | `Ctrl` + `0` |

Shortcut availability can depend on the exact application version and keyboard layout.

### Export attached files

1. Open the relevant saved project.
2. Select **Export Files**.
3. Enter the project's password if requested.
4. Choose the destination folder.
5. Allow the export process to complete.
6. Check the destination folder for the exported files.

Only files available to the export operation can be copied successfully.

### Save and reopen projects

1. Save the workspace to a `.dasweic` file.
2. Keep the file in a safe local location.
3. Use the application's Open Project action to reopen it.
4. Enter the required password when prompted.

Do not delete your only copy of a project before verifying that its backup opens correctly.

---

## 📁 Project Structure

```text
Dasweic-Notes/
├── main.py             # Main desktop application
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation
```

The application source is designed to remain in a single Python file. The README and dependency manifest are supporting project files.

---

## 🔒 Privacy & Offline Operation

Dasweic Notes is designed around local desktop usage.

- Projects are saved locally.
- Imported files originate from local storage.
- No cloud account is required for the described workflow.
- Project encryption is handled by the application's local cryptographic implementation.
- Exported attachments are written to a folder selected by the user.

Do not assume that every dependency or operating-system component is automatically free of network activity. For strict offline environments, install dependencies beforehand, disconnect networking if required, and independently verify runtime behavior.

### Password safety

- Use a strong password where the application supports password changes.
- Keep a secure backup of important projects.
- Never share your project password with untrusted people.
- Test recovery and reopening procedures before relying on encrypted projects for critical data.

Losing the required password may make encrypted project contents unrecoverable.

---

## 🧰 Troubleshooting

### PySide6 is missing

Install the dependencies:

```bash
python -m pip install PySide6 cryptography
```

### Cryptography import error

Run:

```bash
python -m pip install --upgrade cryptography
```

### PDF viewer is unavailable

Install the optional PDF fallback:

```bash
python -m pip install PyMuPDF
```

Some PDF functionality may also require compatible Qt PDF modules.

### Audio or video does not play

- Check whether the installed PySide6 distribution includes Qt Multimedia.
- Verify that your operating system has the necessary codecs.
- Try a common supported media format.
- Confirm that the file is accessible and not corrupted.

### Application does not start

1. Confirm the Python version.
2. Install all required dependencies.
3. Run the application from a terminal.
4. Read the full error traceback.
5. Verify that the correct `main.py` is being executed.

### Project cannot be opened

- Confirm that the selected file is a valid `.dasweic` project.
- Verify the password.
- Check that the file is not incomplete or corrupted.
- Try opening a backup if available.

---

## 🔄 Backups & Data Management

Recommended practices:

- Save projects regularly.
- Keep at least one backup of important projects.
- Export important attachments when you need standalone copies.
- Store backups on a separate drive when appropriate.
- Verify that backups can be reopened before deleting older versions.
- Avoid editing the same project file simultaneously from multiple processes.

---

## 🗺️ Roadmap

Possible future improvements include:

- More advanced text-box layout and resizing.
- Additional canvas object types and formatting.
- More comprehensive keyboard customization.
- Improved project recovery and backup workflows.
- Expanded document and media compatibility.
- Enhanced accessibility and navigation.

These are potential improvements, not promises that they are already implemented.

---

## 🤝 Contributing

If you plan to modify the project:

1. Keep the single-file application architecture unless the project requirements change.
2. Preserve existing project compatibility wherever possible.
3. Test save and reopen workflows after editing project serialization.
4. Test encryption and export behavior with non-sensitive sample data.
5. Avoid committing passwords, private projects, or personal attachments.
6. Document new dependencies and features.

---

## ⚠️ Disclaimer

Dasweic Notes is provided as a desktop software project. Compatibility depends on the Python version, installed libraries, operating system, hardware, codecs, and file formats.

Encryption does not replace secure password management or backups. Always validate important data before deleting original files.

---

## 📜 License

No license has been specified in this README.

Before distributing or publishing the project, add a license that clearly defines permitted use, modification, and redistribution.

---

## ✦ Dasweic Notes

**Capture your thoughts. Connect your ideas. Build your own universe.**
