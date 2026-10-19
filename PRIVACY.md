# WinDrop / WinDropX privacy policy

_Last updated: October 2026_

WinDrop (sold in the Microsoft Store as **WinDrop X**) lets you send files between your phone and your Windows PC over your own Wi-Fi network.

## What we collect

**Nothing.** WinDrop has no accounts, no analytics, no advertising and no tracking. The developer never receives your files, your device details or any usage data.

## How your files move

- Files travel directly between your phone and your PC over your local network. They are never uploaded to the internet or to any server run by the developer.
- Files you receive are saved on your PC in `Downloads\WinDrop`. Files you choose to share are copied to `Downloads\WinDrop\Send to iPhone`. You can delete them at any time.

## Sending to a far laptop

When you use *Send to a far laptop*, your files travel over the internet to the other laptop. They are encrypted end to end on your PC using the code you share, so only the laptop that enters that code can read them. To connect two laptops on different networks, the transfer passes through a relay server operated by the open-source croc project; the relay only ever sees encrypted data and does not store files. The developer of WinDrop never receives your files.

## Data stored on your PC

WinDrop keeps a small settings file on your PC containing: the private connection key shown in the QR code, the list of devices you approved (a random device ID, a device type such as "iPhone (Safari)", its local network address and when it was last used), and the names of networks you chose to trust. This file never leaves your PC. Uninstalling the app removes it.

## Network access

WinDrop runs a small web server on your PC so your phone can connect over your local network. Only devices you approve on the PC can use it, and it refuses connections on public networks unless you choose to trust them.

## Children

WinDrop does not knowingly collect any information from anyone, including children.

## Contact

Questions about privacy: open an issue at https://github.com/Gihan007/WinDrop/issues
