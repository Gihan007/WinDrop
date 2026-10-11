# WinDrop

Send files between your iPhone and your Windows laptop over Wi-Fi. No cable, no cloud, no mobile data, and nothing to install on the iPhone.

WinDrop runs on your laptop and shows a QR code. Scan it with your iPhone camera, and Safari opens a page where you can send photos and files to the laptop, or download files the laptop has shared.

## Download

Go to the [Releases](../../releases) page and download **WinDrop-Setup.exe** (installer) or **WinDrop.exe** (portable, no install).

The first time you run it, Windows may show two warnings:

- **"Windows protected your PC"**: click **More info**, then **Run anyway**. This appears because the app isn't code-signed, which costs money for open-source projects.
- **Windows Firewall**: tick **Private networks** and click **Allow**. Without this, your iPhone can't reach the laptop.

## How to use

1. Connect your iPhone and laptop to the **same Wi-Fi**.
2. Open WinDrop on the laptop.
3. Point your iPhone camera at the QR code and tap the link.
4. **iPhone to laptop:** tap *Choose photos or files*. Files are saved to `Downloads\WinDrop`.
5. **Laptop to iPhone:** click *Send files to iPhone…* in WinDrop, then tap *Refresh list* on the iPhone and tap a file to download it.

Tip: in Safari, tap Share, then *Add to Home Screen* to open WinDrop like an app next time.

No Wi-Fi around? Turn on **Mobile hotspot** on the laptop (Settings > Network & Internet), join it from the iPhone, and pick the hotspot address (usually `192.168.137.1`) in WinDrop's *Network address* menu.

## Privacy and security

- Files go straight from the phone to the laptop over your local network. Nothing is uploaded to the internet.
- The QR code contains a private key. Other people on the same Wi-Fi can't use WinDrop without scanning it.
- Click **New link** to disconnect every phone that connected before.
- On public Wi-Fi (cafés, airports), close WinDrop when you're done.

## Run from source

```
pip install -r requirements.txt
python src/app.py
```

## Build the .exe yourself

On Windows, double-click `build.bat`. The app appears at `dist\WinDrop.exe`.

## Publish a new release (automatic)

The GitHub Actions workflow builds the app on GitHub's free Windows servers.

```
git tag v1.0.0
git push origin v1.0.0
```

A few minutes later, `WinDrop-Setup.exe` and `WinDrop.exe` appear on the Releases page.

## License

Apache License 2.0. See [LICENSE](LICENSE).
