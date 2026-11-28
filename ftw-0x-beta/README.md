# FTW (beta)

FTW plans your battery, car charging and solar around electricity prices and
controls them, here on your Home Assistant.

> **Next steps**
>
> 1. **Install**, then **Start**. The first install builds the app on your
>    device and takes a few minutes.
> 2. Choose **Open Web UI**.
> 3. On the **Info** tab, turn on **Show in sidebar**, and **Watchdog** so
>    Home Assistant restarts FTW if it stops answering.
> 4. Follow FTW's setup guide: your home, then your devices.
> 5. For Home Assistant entities, add the **Mosquitto broker** app and the
>    **MQTT** integration Home Assistant offers, then restart FTW.

**Why host network.** FTW searches your home network for devices, talks to
inverters and meters over Modbus TCP, and lets OCPP chargers dial in to it.
That needs Home Assistant's own network, which also lowers the app's
protection rating in the store.

Pairing and using the FTW app on your phone go through FTW Cloud, so they need
internet. Control runs on the box, here your Home Assistant.

Beta: every FTW beta arrives as an update. Only one FTW may control a home, so
stop any other FTW (an old app or another computer) before this one controls
equipment. Full steps are on the **Documentation** tab ([DOCS.md](DOCS.md)).
