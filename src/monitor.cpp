#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusObjectPath>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusServiceWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QSet>
#include <QSocketNotifier>
#include <QTimer>
#include <QVariantMap>
#include <cstdio>
#include <csignal>
#include <cstring>
#include <wayland-client.h>
#include "wlr-foreign-toplevel-management-client.h"

class Monitor : public QObject {
    Q_OBJECT
public:
    struct Output { Monitor *owner; uint32_t id; wl_output *handle; QString name; };
    struct Top {
        Monitor *owner;
        zwlr_foreign_toplevel_handle_v1 *handle;
        QString title, appId;
        QSet<wl_output *> outputs;
        bool fullscreen = false, activated = false;
    };
    wl_display *display = nullptr;
    wl_registry *registry = nullptr;
    zwlr_foreign_toplevel_manager_v1 *manager = nullptr;
    QMap<uint32_t, Output *> outputs;
    QSet<Top *> tops;
    QDBusConnection bus = QDBusConnection::systemBus();
    QTimer flushTimer, refreshTimer;
    QString session;
    QJsonObject power{{"power_available", false}, {"session_available", false},
        {"on_battery", false}, {"percentage", QJsonValue::Null},
        {"locked", false}, {"sleeping", false}, {"session_active", true}};

    Monitor() {
        flushTimer.setSingleShot(true);
        flushTimer.setInterval(40);
        connect(&flushTimer, &QTimer::timeout, this, &Monitor::publish);
        refreshTimer.setSingleShot(true);
        refreshTimer.setInterval(80);
        connect(&refreshTimer, &QTimer::timeout, this, &Monitor::refresh);
        bus.connect("org.freedesktop.UPower", "", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                    this, SLOT(properties(QString,QVariantMap,QStringList)));
        bus.connect("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                    "PrepareForSleep", this, SLOT(sleeping(bool)));
        auto *services = new QDBusServiceWatcher("org.freedesktop.UPower", bus,
            QDBusServiceWatcher::WatchForOwnerChange, this);
        services->addWatchedService("org.freedesktop.login1");
        connect(services, &QDBusServiceWatcher::serviceOwnerChanged, this,
            [this](const QString &name, const QString &, const QString &) {
                if (name == "org.freedesktop.UPower") power["power_available"] = false;
                else { power["session_available"] = false; session.clear(); }
                refresh(); changed();
            });
        display = wl_display_connect(nullptr);
        if (display) {
            registry = wl_display_get_registry(display);
            static const wl_registry_listener listener{global, removed};
            wl_registry_add_listener(registry, &listener, this);
            if (wl_display_roundtrip(display) < 0 || wl_display_roundtrip(display) < 0) {
                QTimer::singleShot(0, this, [] { QCoreApplication::exit(2); });
            } else {
                auto *notifier = new QSocketNotifier(wl_display_get_fd(display), QSocketNotifier::Read, this);
                connect(notifier, &QSocketNotifier::activated, this, [this] {
                    if (wl_display_dispatch(display) < 0) QCoreApplication::exit(2);
                    else wl_display_flush(display);
                });
                wl_display_flush(display);
            }
        }
        refresh(); changed();
    }
    ~Monitor() override {
        for (auto *top : tops) { zwlr_foreign_toplevel_handle_v1_destroy(top->handle); delete top; }
        for (auto *output : outputs) { wl_output_release(output->handle); delete output; }
        if (manager) zwlr_foreign_toplevel_manager_v1_destroy(manager);
        if (registry) wl_registry_destroy(registry);
        if (display) wl_display_disconnect(display);
    }
    void changed() { if (!flushTimer.isActive()) flushTimer.start(); }
    void publish() {
        QJsonObject snapshot = power;
        snapshot["version"] = 1;
        snapshot["event"] = "environment";
        snapshot["foreign_available"] = manager != nullptr;
        QJsonArray windows;
        for (auto *top : tops) {
            QJsonArray names;
            for (auto *out : outputs)
                if (top->outputs.contains(out->handle) && !out->name.isEmpty()) names.append(out->name);
            windows.append(QJsonObject{{"app_id", top->appId}, {"title", top->title}, {"outputs", names},
                {"fullscreen", top->fullscreen}, {"activated", top->activated}});
        }
        snapshot["toplevels"] = windows;
        const auto bytes = QJsonDocument(snapshot).toJson(QJsonDocument::Compact) + '\n';
        if (fwrite(bytes.data(), 1, size_t(bytes.size()), stdout) != size_t(bytes.size()) || fflush(stdout) != 0)
            QCoreApplication::quit();
    }
    void getAll(const QString &service, const QString &path, const QString &interface) {
        auto call = QDBusMessage::createMethodCall(service, path, "org.freedesktop.DBus.Properties", "GetAll");
        call << interface;
        auto *watcher = new QDBusPendingCallWatcher(bus.asyncCall(call, 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, interface, watcher] {
            QDBusPendingReply<QVariantMap> reply = *watcher;
            watcher->deleteLater();
            if (reply.isError()) {
                if (interface == "org.freedesktop.UPower") power["power_available"] = false;
                if (interface == "org.freedesktop.login1.Session") power["session_available"] = false;
                changed(); return;
            }
            const auto properties = reply.value();
            if (interface == "org.freedesktop.UPower") {
                power["power_available"] = properties.contains("OnBattery");
                power["on_battery"] = properties.value("OnBattery").toBool();
            } else if (interface == "org.freedesktop.UPower.Device") {
                power["percentage"] = properties.value("IsPresent").toBool()
                    ? QJsonValue(properties.value("Percentage").toDouble()) : QJsonValue(QJsonValue::Null);
            } else {
                power["session_available"] = true;
                power["locked"] = properties.value("LockedHint").toBool();
                power["session_active"] = properties.value("Active", true).toBool();
            }
            changed();
        });
    }
public slots:
    void properties(const QString &, const QVariantMap &, const QStringList &) { refreshTimer.start(); }
    void lock() { power["locked"] = true; changed(); }
    void unlock() { power["locked"] = false; changed(); }
    void sleeping(bool value) { power["sleeping"] = value; changed(); if (!value) refresh(); }
    void refresh() {
        getAll("org.freedesktop.UPower", "/org/freedesktop/UPower", "org.freedesktop.UPower");
        getAll("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice", "org.freedesktop.UPower.Device");
        if (!session.isEmpty()) {
            getAll("org.freedesktop.login1", session, "org.freedesktop.login1.Session");
            return;
        }
        auto call = QDBusMessage::createMethodCall("org.freedesktop.login1", "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager", qEnvironmentVariableIsSet("XDG_SESSION_ID") ? "GetSession" : "GetSessionByPID");
        if (qEnvironmentVariableIsSet("XDG_SESSION_ID")) call << qEnvironmentVariable("XDG_SESSION_ID");
        else call << uint(QCoreApplication::applicationPid());
        auto *watcher = new QDBusPendingCallWatcher(bus.asyncCall(call, 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher] {
            QDBusPendingReply<QDBusObjectPath> reply = *watcher;
            watcher->deleteLater();
            if (reply.isError() || !session.isEmpty()) return;
            session = reply.value().path();
            bus.connect("org.freedesktop.login1", session, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                this, SLOT(properties(QString,QVariantMap,QStringList)));
            bus.connect("org.freedesktop.login1", session, "org.freedesktop.login1.Session", "Lock", this, SLOT(lock()));
            bus.connect("org.freedesktop.login1", session, "org.freedesktop.login1.Session", "Unlock", this, SLOT(unlock()));
            getAll("org.freedesktop.login1", session, "org.freedesktop.login1.Session");
        });
    }
private:
    static void global(void *data, wl_registry *registry, uint32_t id, const char *interface, uint32_t version) {
        auto *self = static_cast<Monitor *>(data);
        if (strcmp(interface, "wl_output") == 0 && version >= 4) {
            auto *out = new Output{self, id, static_cast<wl_output *>(wl_registry_bind(registry, id, &wl_output_interface, 4)), {}};
            static const wl_output_listener listener{
                [](void *, wl_output *, int32_t, int32_t, int32_t, int32_t, int32_t, const char *, const char *, int32_t) {},
                [](void *, wl_output *, uint32_t, int32_t, int32_t, int32_t) {},
                [](void *p, wl_output *) { static_cast<Output *>(p)->owner->changed(); },
                [](void *, wl_output *, int32_t) {},
                [](void *p, wl_output *, const char *name) { static_cast<Output *>(p)->name = QString::fromUtf8(name); },
                [](void *, wl_output *, const char *) {}};
            wl_output_add_listener(out->handle, &listener, out);
            self->outputs[id] = out;
        } else if (strcmp(interface, "zwlr_foreign_toplevel_manager_v1") == 0 && version >= 2) {
            self->manager = static_cast<zwlr_foreign_toplevel_manager_v1 *>(
                wl_registry_bind(registry, id, &zwlr_foreign_toplevel_manager_v1_interface, qMin(version, 3u)));
            static const zwlr_foreign_toplevel_manager_v1_listener listener{
                [](void *p, zwlr_foreign_toplevel_manager_v1 *, zwlr_foreign_toplevel_handle_v1 *handle) {
                    auto *owner = static_cast<Monitor *>(p);
                    auto *top = new Top{owner, handle, {}, {}, {}, false, false};
                    owner->tops.insert(top);
                    static const zwlr_foreign_toplevel_handle_v1_listener topListener{
                        [](void *t, auto *, const char *v) { static_cast<Top *>(t)->title = QString::fromUtf8(v); },
                        [](void *t, auto *, const char *v) { static_cast<Top *>(t)->appId = QString::fromUtf8(v); },
                        [](void *t, auto *, wl_output *o) { static_cast<Top *>(t)->outputs.insert(o); },
                        [](void *t, auto *, wl_output *o) { static_cast<Top *>(t)->outputs.remove(o); },
                        [](void *t, auto *, wl_array *states) {
                            auto *top = static_cast<Top *>(t);
                            top->fullscreen = false; top->activated = false;
                            auto *values = static_cast<uint32_t *>(states->data);
                            for (size_t i = 0; i < states->size / sizeof(uint32_t); ++i) {
                                if (values[i] == ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_FULLSCREEN) top->fullscreen = true;
                                if (values[i] == ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_ACTIVATED) top->activated = true;
                            }
                        },
                        [](void *t, auto *) { static_cast<Top *>(t)->owner->changed(); },
                        [](void *t, auto *handle) {
                            auto *top = static_cast<Top *>(t);
                            top->owner->tops.remove(top); top->owner->changed();
                            zwlr_foreign_toplevel_handle_v1_destroy(handle); delete top;
                        },
                        [](void *, auto *, auto *) {}};
                    zwlr_foreign_toplevel_handle_v1_add_listener(handle, &topListener, top);
                },
                [](void *p, zwlr_foreign_toplevel_manager_v1 *manager) {
                    auto *self = static_cast<Monitor *>(p);
                    zwlr_foreign_toplevel_manager_v1_destroy(manager);
                    self->manager = nullptr; self->changed();
                }};
            zwlr_foreign_toplevel_manager_v1_add_listener(self->manager, &listener, self);
        }
    }
    static void removed(void *data, wl_registry *, uint32_t id) {
        auto *self = static_cast<Monitor *>(data);
        auto *out = self->outputs.take(id);
        if (!out) return;
        for (auto *top : self->tops) top->outputs.remove(out->handle);
        wl_output_release(out->handle); delete out; self->changed();
    }
};

int main(int argc, char **argv) {
    std::signal(SIGPIPE, SIG_IGN);
    QCoreApplication app(argc, argv);
    Monitor monitor;
    return app.exec();
}
#include "monitor.moc"
