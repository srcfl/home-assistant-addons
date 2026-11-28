# FTW (beta)

FTW plans your battery, car charging and solar around electricity prices and
controls them, here on your Home Assistant.

> **Next steps**
>
> 1. **Install**, then **Start**.
> 2. Choose **Open Web UI**.
> 3. On the **Info** tab, turn on **Show in sidebar**, and **Watchdog** so
>    Home Assistant restarts FTW if it stops answering.
> 4. Follow FTW's setup guide: your home, then your devices.
> 5. For Home Assistant entities, add the **Mosquitto broker** app and the
>    **MQTT** integration Home Assistant offers, then restart FTW.

**Why host network.** FTW uses Home Assistant's own network so it can search
your home network for inverters, meters and chargers, find devices by their
`.local` names, and let OCPP chargers dial in at Home Assistant's address
(port 8887 by default). Host networking also lowers the app's protection
rating in the store.

Pairing turns on FTW Cloud and accepts its [terms](https://ftw.energy/privacy).
The FTW app on your phone then connects through FTW Cloud, so pairing and the
phone app need internet. Control runs on your Home Assistant.

Beta: every FTW beta arrives as an update. Only one FTW may control a home, so
stop any other FTW (an old app or another computer) before this one controls
equipment. Full steps are on the **Documentation** tab ([DOCS.md](DOCS.md)).
