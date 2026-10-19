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

6. **Download on laptop** (tick *Allow laptop downloads* in WinDrop first): paste a magnet link, torrent link or any download link (or pick a `.torrent` file). The laptop downloads it and it appears under *Laptop to iPhone* when finished. Downloads go to `Downloads\WinDrop\Send to iPhone\Torrents`.

7. **Send to a far laptop:** click *Send to a far laptop…*, pick files, and share the code it shows (for example `4821-amber-river-stone`). On the other laptop, anywhere in the world, click *Receive with a code…* and type it. Files arrive in `Downloads\WinDrop\From far away`. Both laptops must stay on until it finishes; if the connection drops, it continues by itself. Any size works.

Big uploads from the iPhone are sent in pieces, several at once, and resume automatically if the connection drops or the phone locks. If a transfer pauses, choose the same file again to continue where it stopped.

Tip: in Safari, tap Share, then *Add to Home Screen* to open WinDrop like an app next time.

No Wi-Fi around? Turn on **Mobile hotspot** on the laptop (Settings > Network & Internet), join it from the iPhone, and pick the hotspot address (usually `192.168.137.1`) in WinDrop's *Network address* menu.

## About laptop downloads

- Laptop downloads use the **laptop's internet connection**. If the laptop is on your iPhone's hotspot, they use your mobile data.
- Seeding (sharing back to other people) stops as soon as a torrent finishes.
- Only download content you have the right to download. Torrents are a common way malware spreads; WinDrop flags program files such as `.exe` so you can think twice before opening them.

## Privacy and security

- **Files stay on your network.** They go straight from the phone to the laptop; nothing is uploaded to the internet.
- **Every new device needs your approval.** The first time a phone connects, the laptop asks *"iPhone wants to connect. Allow?"* Nothing works until you click Allow. Manage allowed devices with the **Devices** button; devices unused for 30 days must be approved again.
- **Unguessable link.** The QR code contains a 32-character key. After 10 wrong guesses, a device is blocked for 15 minutes.
- **Public networks are blocked.** On networks Windows marks as public, WinDrop refuses connections until you click *Trust this network*. Only trust your own hotspot or home Wi-Fi.
- **New link** creates a new key and removes every allowed device.
- **Laptop downloads are off by default.** When on, they can't target addresses inside your own network (like your router).
- **Far transfers are end-to-end encrypted.** The code is used to set up encryption, so the relay server that connects the two laptops only ever sees scrambled data. They use the laptop's internet connection: on a phone hotspot, that means mobile data.
- **Limitation:** transfers use plain `http`, so they're not encrypted. Use WinDrop on your home Wi-Fi or your own iPhone hotspot, not on café, airport or hotel Wi-Fi.

## Microsoft Store edition

The Store edition is called **WinDrop X** (Store ID 9P8DP2ZLS077). It's built automatically as an MSIX package by GitHub Actions (artifact *WinDropX-Microsoft-Store*). It doesn't include laptop downloads, and its firewall permission is part of the package, so it installs without any prompts. Submission text is in [`store/LISTING.md`](store/LISTING.md); privacy policy in [`PRIVACY.md`](PRIVACY.md).

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

## Third-party software

Far transfers are powered by [croc](https://github.com/schollz/croc) (MIT), downloaded during the build (checksum verified) and shipped unmodified. By default it connects through croc's public relay; transfers are end-to-end encrypted.

Laptop downloads are powered by [aria2](https://github.com/aria2/aria2) (GPL-2.0, with OpenSSL exception), which is downloaded during the build and shipped unmodified as a separate program. Its license files are included in the app bundle.

## License

Apache License 2.0. See [LICENSE](LICENSE).
