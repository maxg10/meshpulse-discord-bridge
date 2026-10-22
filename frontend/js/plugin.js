/**
 * Discord Bridge — frontend.
 *
 * Renders a compact status panel on the map and mirrors the backend's
 * "status" WebSocket channel. All state originates from the backend; this
 * layer is purely presentational.
 */
var DiscordBridgePlugin = (function () {
    "use strict";

    var STATUS = {
        online:       { label: "online",            tone: "ok" },
        offline:      { label: "offline",           tone: "err" },
        reconnecting: { label: "reconnecting",      tone: "warn" },
        starting:     { label: "starting",          tone: "warn" },
        unconfigured: { label: "not configured",    tone: "warn" },
        bad_token:    { label: "invalid token",     tone: "err" },
        no_intent:    { label: "intent missing",    tone: "err" },
        bad_channel:  { label: "channel error",     tone: "err" },
        disabled:     { label: "disabled",          tone: "err" }
    };

    var TONE_TO_NOTIFICATION = { ok: "success", err: "error", warn: "info" };

    function Plugin() {
        this.api = null;
        this.root = null;
        this.lastStatus = null;
    }

    Plugin.prototype.onEnable = function (api) {
        this.api = api;

        var root = document.createElement("div");
        root.className = "dbr-panel";
        root.innerHTML =
            '<div class="dbr-head">' +
                '<span class="dbr-dot warn"></span>' +
                '<span class="dbr-title">Discord Bridge</span>' +
            '</div>' +
            '<div class="dbr-state">initialising…</div>' +
            '<div class="dbr-counters">' +
                '<span class="dbr-rx" title="Mesh to Discord">&darr; 0</span>' +
                '<span class="dbr-tx" title="Discord to mesh">&uarr; 0</span>' +
            '</div>';

        this.root = root;
        // MeshPulse 2.6.1+ hosts plugin panels itself: on the desktop they share
        // one column and (from 2.8.0) get a drag grip, on phones they move into
        // the Map Layers drawer. Older cores only have plain Leaflet controls.
        if (api.panels && api.panels.register) {
            api.panels.register(root);
        } else {
            api.map.addControl("dbr-status", root, "bottomleft");
        }

        var self = this;
        api.ws.subscribe("status", function (payload) {
            self.render(payload);
        });

        // Repaint from the last known state so the panel is not blank until
        // the backend next pushes an update.
        var cached = api.storage.get("lastStatus");
        if (cached) {
            this.render(cached);
        }
    };

    Plugin.prototype.render = function (payload) {
        if (!this.root || !payload || payload.type !== "bridge_status") {
            return;
        }

        var status = STATUS[payload.status] || { label: payload.status, tone: "warn" };

        this.root.querySelector(".dbr-dot").className = "dbr-dot " + status.tone;
        this.root.querySelector(".dbr-state").textContent = status.label;
        this.root.querySelector(".dbr-rx").innerHTML = "&darr; " + (payload.mesh_to_discord || 0);
        this.root.querySelector(".dbr-tx").innerHTML = "&uarr; " + (payload.discord_to_mesh || 0);

        // Notify on transitions only, and never on the first paint.
        if (payload.status !== this.lastStatus) {
            if (this.lastStatus !== null) {
                this.api.ui.showNotification(
                    "Discord Bridge: " + status.label,
                    TONE_TO_NOTIFICATION[status.tone] || "info"
                );
            }
            this.lastStatus = payload.status;
        }

        this.api.storage.set("lastStatus", payload);
    };

    Plugin.prototype.onDisable = function (api) {
        api.ws.unsubscribe("status");
        if (api.panels && api.panels.unregister && this.root) {
            api.panels.unregister(this.root);
        } else {
            api.map.removeControl("dbr-status");
        }
        this.root = null;
        this.lastStatus = null;
    };

    Plugin.prototype.onConfigUpdate = function () {
        // Configuration is applied backend-side; nothing to repaint here.
    };

    return Plugin;
})();

// Required by the MeshPulse plugin loader.
window.MeshPlugin = DiscordBridgePlugin;
