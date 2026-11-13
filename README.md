# ARES Console

A net control station (NCS) console for ARES and other emergency nets. It runs on your computer and you use it in your web browser.

## Install

Download from **[Releases](https://github.com/scottws70/ARES-Console/releases/latest)**:

- **Windows 10/11**: run `ARES-Console-<version>-Windows-Setup.exe` (Python is included; no admin rights needed). Or unzip the Portable zip and run `ARES Console.cmd`.
- **Debian, Ubuntu, Mint, Raspberry Pi OS**: `sudo apt install ./ares-console_<version>_all.deb`
- **Other Linux**: unpack `ares-console-<version>-linux.tar.gz` and run `./install.sh` (per-user, no root).

Then start **ARES Console** from your applications menu. It opens in your browser at http://127.0.0.1:8073/. Starting it again just reopens that page. To stop it, use **Settings › Quit ARES Console**; on Windows you can also close its minimized window.

### Run from source

You only need Python 3.8 or newer: no pip installs and no build step.

```bash
./ares-console                 # opens http://127.0.0.1:8073/
./ares-console --host 0.0.0.0  # also let other PCs on the LAN (e.g. a logger) use it
./ares-console --data /path    # use a different data folder
```

Your logs and settings are kept in one SQLite file, `ares.db`, in the data folder: `~/.local/share/ares-console` on Linux, `%LOCALAPPDATA%\ARES-Console` on Windows. Installing, upgrading or uninstalling never touches it. Back it up after an event.

### Building the installers

`packaging/linux/build.sh` builds the `.deb` and the tarball. `packaging/windows/build.ps1` builds the Windows installer and portable zip (it needs Inno Setup 6). Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds both, installs and tests them on clean Linux and Windows machines, and publishes a GitHub release.

## Features

| Area | What it does |
|---|---|
| **Header** | Sets your organization's title and subtitle (e.g. "Cass County ARES"), shows UTC and local clocks, and shows the status of APRS, JS8Call and Winlink. |
| **Net Log** | Open a net, then check stations in quickly (press Enter). The roster shows callsign, name, tactical call, **status (Present / Away / Checked Out, configurable)**, location and notes, all editable in place. Every change is timestamped in the activity log, and you can add manual log entries. |
| **APRS Map** | Each station checked in is **added to the APRS-IS filter automatically** (`b/CALL*`) and tracked live, with tracks. If a station has no APRS, type a grid square or `lat, lon` in its Location and it is plotted. Click **Drop location** to place EOC, Shelter, Staging, Spot 1 and similar markers. Markers can be dragged and edited. |
| **Forms** | Built-in **ICS-213** (create as many as you need, incoming or outgoing), **ICS-214** (imports the roster and the net activity log), **ICS-205**, **ICS-309** (imports traffic), and the **NTS Radiogram** (counts the check automatically and produces standard radiogram format). Every form is saved to the form log and can be opened, copied, printed, or sent by Winlink or JS8Call. |
| **Winlink Standard Forms** | The whole Winlink forms library: the same HTML templates that Winlink Express and Pat use. Completed forms are sent with the `RMS_Express_Form_*.xml` attachment, so Winlink Express users see the formatted form. Received forms open in their viewer. |
| **SitRepNet MCForms** | One click downloads the current JS8Spotter MCForms set (F!103, F!304, F!309 and the rest) from sitrepnet.com. Fill one in to get the compact `F!304 1213…` string and send it over JS8Call. Received F! strings are decoded in the JS8 tab. |
| **Winlink** | Inbox, Outbox, Sent and On Server lists, plus compose, reply and forward. Connects over **ARDOP** (ardopc/ardopcf host TCP), **Telnet to CMS** (Internet fallback), or **Telnet P2P**. When mail is waiting you get a list of messages to choose from. Messages you don't choose stay on the server (B2F "defer") and appear under **On Server**, where you can download them later. |
| **Gateways** | Gateway list with callsign, dial frequency, mode, bandwidth, grid, hours and notes. Favorites sort first. **Import the ARDOP gateway list from Pat** (`pat rmslist`), sorted by distance. |
| **Radio** | Hamlib `rigctld`: shows the frequency and mode, sets the frequency (it tunes to the gateway before an ARDOP call), and keys PTT when ARDOP asks. |
| **JS8Call** | Uses the JS8Call TCP API to send messages and log directed traffic. A grid square from a checked-in station updates its map position. |
| **Reports** | When you close the net, you can open a printable **net summary**: statistics, roster with times in and out, last positions, map locations, the full activity log, Winlink and JS8 traffic, and the text of every form. It can be saved as PDF or HTML. |

## VFO and waterfall

The Winlink and JS8Call tabs have a radio strip at the top:

- **VFO readout**: the dial frequency and mode from rigctld, or from JS8Call if rig control is off, refreshed every second. Type a frequency in kHz and press **Tune** to change it.
- **JS8 band buttons** (80, 40, 30, 20, 15, 10 m) tune to the standard JS8 dial frequencies: 3.578, 7.078, 10.130, 14.078, 21.078 and 28.078 MHz, USB. When JS8Call is connected the tuning goes through JS8Call so it stays in sync; otherwise it goes through rigctld.
- **Waterfall** (0–3000 Hz audio) from the radio's sound card. Press **Start**, allow microphone access, and pick the rig's USB audio input. It turns itself back on next time.
  - On the JS8 tab, a red mark shows your transmit offset. Click the waterfall to move it.
  - On the Winlink tab, the shaded area is the ARDOP passband.
  - Audio is analyzed in the browser and never stored. With PipeWire or PulseAudio, the waterfall can share the sound card with JS8Call and ardopcf. With raw ALSA `hw:` devices, only one program can open the card at a time.

## Offline map

The map keeps working when the Internet or power goes out (the app and its map library are bundled locally; nothing loads from a CDN).

- **Every tile you look at is saved** in `<data>/tiles/` and used whenever the Internet is down. If a close-up tile was never saved, the nearest saved lower-zoom tile is enlarged to fill in, so you never get a blank map.
- **Save visible area** (Map tab › Offline Map): before an event, zoom to your county, pick a zoom range (e.g. 9–15) and save. It shows the tile count and size first and allows up to 20,000 tiles per download (about 500 MB).
- **Map sources** (Settings › Map): *USGS Topo* (the default) and *USGS Imagery + Topo* are public domain US government maps and may be saved for offline use. *OpenStreetMap* is **online only**: the OSM Foundation's tile policy prohibits bulk and offline downloading from its servers, so ARES Console loads OSM directly and never saves it. You can also point it at your own tile server.
- **Offline packs**: copy any raster `.mbtiles` file into `<data>/tiles/` and it is used first.

## Setup checklist

1. **Settings**: set the title and subtitle, your callsign, grid and map home location.
2. **APRS-IS**: works out of the box in receive-only mode (passcode -1).
3. **Radio**: run `rigctld -m <model> -r /dev/ttyUSB0 -t 4532` and tick *Radio enabled*.
4. **ARDOP**: run `ardopcf 8515 <capture> <playback>` and enter your Winlink password in Settings. Leave *Key PTT through rigctld* ticked unless ardopcf keys the radio itself.
5. **JS8Call**: in JS8Call open Settings › Reporting and enable the TCP Server API (port 2442), then tick *JS8 enabled*.
6. **Winlink forms**: the app finds Pat's `~/.local/share/pat/Standard_Forms` automatically. Refresh it with `pat templates update`, or point Settings at any Standard_Forms folder.

## Notes and limitations

- The Winlink B2F protocol and its compression are implemented natively. They were tested end to end against Pat (send, receive, choosing what to download, deferring). **Over the air on ARDOP and against the live CMS they have not been tested yet**, so try a session before you rely on them in an event.
- The From and Subject in the "messages waiting" list come from `;PM:` lines, when the server sends them. A P2P station such as Pat sends only the message ID and size.
- The compact MCForms string follows the MCForms file layout: one code per question, then `[TAG]text`. Check it against JS8Spotter before you use it on the air.
- By default the server listens on localhost only. If you use `--host 0.0.0.0`, only do it on a trusted network, because there is no login.
