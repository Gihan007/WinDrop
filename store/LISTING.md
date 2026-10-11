# Microsoft Store submission: text to copy into Partner Center

Partner Center: https://partner.microsoft.com/dashboard/apps-and-games/overview

---

## Properties

- **Category:** Utilities & tools (subcategory: File managers, if offered)
- **Privacy policy URL:** https://github.com/Gihan007/WinDrop/blob/main/PRIVACY.md
- **Website:** https://github.com/Gihan007/WinDrop
- **Support contact:** https://github.com/Gihan007/WinDrop/issues
- **Product declarations:** tick nothing unless a question clearly applies. The app does not use your camera, microphone, location or any accounts.
- **"This product accesses, collects, or transmits personal information":** answer **No**. The app collects nothing; files move only between the user's own devices on their own network. (If the form insists because of network access, answer Yes and use the privacy policy URL above.)

## Age ratings (IARC questionnaire)

- Category: **All other app types**
- Violence, fear, sexuality, gambling, drugs, language: **No** to all
- **Does the app allow users to interact or exchange content?** Yes: users can share files between their own devices
- **Does the app share the user's current physical location?** No
- **Does the app allow purchases?** No
- Expected result: **3+ / Everyone**

## Store listing (English, United States)

**Product name:** WinDropX

**Short description** (max 100 characters):
> Send photos, videos and files between your iPhone and PC over Wi-Fi. No cable, no cloud, no app.

**Description:**
> WinDropX is the easiest way to move files between your iPhone and your Windows PC.
>
> Open WinDropX, scan the QR code with your iPhone camera, and a page opens in Safari where you can send photos, videos and documents to your PC, or download files from your PC to your phone. There's nothing to install on the iPhone.
>
> FAST AND FULL QUALITY
> Files are copied byte for byte, so a 4K video arrives exactly as it left. Big files are sent in parallel pieces and resume automatically if the connection drops.
>
> PRIVATE BY DESIGN
> Files travel directly over your own Wi-Fi or iPhone hotspot. Nothing is uploaded to the cloud, there are no accounts, and no data is collected. Transfers don't use mobile data.
>
> SECURE
> Every new phone must be approved on your PC before it can connect. The QR code contains a long private key, repeated wrong attempts are blocked, and WinDropX refuses connections on public networks unless you choose to trust them.
>
> HOW IT WORKS
> 1. Connect your iPhone and PC to the same Wi-Fi, or connect the PC to your iPhone's hotspot.
> 2. Open WinDropX and scan the QR code with your iPhone camera.
> 3. Click Allow on your PC the first time.
> 4. Send files in either direction.
>
> Tip: add the page to your iPhone Home Screen to open it like an app.

**What's new in this version:**
> First Microsoft Store release: device approval, resumable transfers, and live transfer speed.

**Product features** (one per line, max 20):
> Send photos and videos from iPhone to PC
> Download files from PC to iPhone
> Nothing to install on the iPhone
> Original quality, byte for byte
> Resumes big transfers automatically
> Works over Wi-Fi or iPhone hotspot
> No mobile data, no cloud, no account
> New devices need your approval

**Search terms** (max 7):
> airdrop for windows, iphone to pc, file transfer, wifi transfer, send photos to pc, iphone file sharing, qr code transfer

**Screenshots:** at least 1, minimum 1366 x 768 pixels. Open WinDropX on your PC and press Win + PrtScn for a full-screen screenshot (saved to Pictures\Screenshots). Suggested:
1. The WinDropX window showing the QR code
2. The approval pop-up ("iPhone wants to connect")
3. A file arriving in the Activity list

**Store logos:** upload `store/StoreListingLogo_300x300.png` as the 1:1 box art / app tile icon if asked.

## Submission options: restricted capability justification

Partner Center will ask why the app uses **runFullTrust**. Paste:

> WinDropX is a classic Windows desktop app (Python/Tkinter) packaged as MSIX. It needs runFullTrust to run as a desktop application: it starts a small local web server so the user's own phone can transfer files to and from the PC over the user's local network, saves received files in the user's Downloads folder, and opens that folder in File Explorer. It does not modify system settings or access files outside its own folders.

**Notes for certification** (optional field, helps reviewers):
> To test: open WinDropX on a PC, then on a phone connected to the same Wi-Fi open the address shown under the QR code (or scan it). Click Allow on the PC when the approval pop-up appears. The phone page can then send files to the PC (saved in Downloads\WinDrop) and download files placed in Downloads\WinDrop\Send to iPhone. Note: on networks Windows marks as Public, the app shows a "Trust this network" button before accepting connections.
