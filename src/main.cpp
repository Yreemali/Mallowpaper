#include <QCommandLineParser>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMediaPlayer>
#include <QQuickItem>
#include <QQuickView>
#include <QScreen>
#include <QSet>
#include <QSocketNotifier>
#include <QTimer>
#include <QVideoFrame>
#include <QVideoSink>
#include <LayerShellQt/Window>
#include <cerrno>
#include <cstdio>
#include <unistd.h>

// stdout is reserved for versioned JSON events; Qt diagnostics go to stderr.
static void emitEvent(QJsonObject event)
{
    event.insert("version", 1);
    const auto line = QJsonDocument(event).toJson(QJsonDocument::Compact) + '\n';
    fwrite(line.constData(), 1, size_t(line.size()), stdout);
    fflush(stdout);
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    app.setApplicationName("mallowpaper-renderer");
    app.setApplicationVersion("0.4.0");
    QCommandLineParser args;
    args.setApplicationDescription("Qt video wallpaper proof. Commands/events are JSON lines on stdin/stdout.");
    args.addHelpOption();
    args.addVersionOption();
    args.addOptions({
        {{"o", "output"}, "Exact Qt/Wayland output name.", "name"},
        {{"f", "file"}, "Local video file.", "path"},
        {"fit", "Placement: fill, fit, or stretch.", "mode", "fill"},
        {"pause-reason", "Hold the first valid frame for this reason (repeatable).", "reason"},
        {"preview", "Use an ordinary window for development."},
        {"list-outputs", "Print outputs and exit."}
    });
    args.process(app);
    if (args.isSet("list-outputs")) {
        QJsonArray outputs;
        for (auto *screen : app.screens()) {
            outputs.append(QJsonObject{{"name", screen->name()},
                {"width", screen->size().width()}, {"height", screen->size().height()},
                {"scale", screen->devicePixelRatio()}});
        }
        emitEvent({{"event", "outputs"}, {"outputs", outputs}});
        return 0;
    }
    auto fail = [](const QString &message) {
        emitEvent({{"event", "error"}, {"message", message}});
        return 2;
    };
    static const QSet<QString> allowed{"manual", "fullscreen", "battery", "low_battery", "lock", "suspend", "output_off"};
    QSet<QString> pauseReasons;
    for (const auto &reason : args.values("pause-reason")) {
        if (!allowed.contains(reason)) return fail("Unknown initial pause reason");
        pauseReasons.insert(reason);
    }
    const QFileInfo file(args.value("file"));
    if (!args.isSet("file") || !file.isFile() || !file.isReadable())
        return fail("--file must name a readable local file");
    const QString fit = args.value("fit");
    if (fit != "fill" && fit != "fit" && fit != "stretch")
        return fail("--fit must be fill, fit, or stretch");
    const bool preview = args.isSet("preview");
    if (!preview && app.platformName() != "wayland")
        return fail("Wallpaper mode requires Wayland; use --preview for development");
    QScreen *target = nullptr;
    for (auto *screen : app.screens())
        if (screen->name() == args.value("output")) target = screen;
    if (!target && preview && !args.isSet("output")) target = app.primaryScreen();
    if (!target) return fail("Output not found; use --list-outputs and specify --output");

    QQuickView view;
    view.setTitle("Video wallpaper preview");
    view.setScreen(target);
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.setColor(Qt::black);
    if (!preview) {
        view.setFlags(Qt::FramelessWindowHint | Qt::WindowDoesNotAcceptFocus | Qt::WindowTransparentForInput);
        auto *layer = LayerShellQt::Window::get(&view);
        layer->setScope("mallowpaper");
        layer->setScreen(target);
        layer->setLayer(LayerShellQt::Window::LayerBackground);
        layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop) | LayerShellQt::Window::AnchorBottom
                          | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight);
        layer->setExclusiveZone(-1);
        layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
        layer->setCloseOnDismissed(true);
        view.resize(target->size());
    } else {
        view.resize(960, 540);
    }
    view.setSource(QUrl("qrc:/qml/Wallpaper.qml"));
    if (view.status() != QQuickView::Ready) return fail("Could not load wallpaper QML");
    auto *video = view.rootObject()->findChild<QObject *>("video");
    auto *sink = video ? video->property("videoSink").value<QVideoSink *>() : nullptr;
    if (!sink) return fail("Qt Multimedia VideoOutput is unavailable");
    // VideoOutput.FillMode: Stretch=0, PreserveAspectFit=1, PreserveAspectCrop=2.
    video->setProperty("fillMode", fit == "stretch" ? 0 : fit == "fit" ? 1 : 2);
    QMediaPlayer player;
    player.setVideoSink(sink);
    player.setLoops(QMediaPlayer::Infinite);
    // No audio output is attached: wallpaper playback must remain silent.
    quint64 frames = 0;
    bool firstFrame = false;
    bool ready = false;
    auto status = [&] {
        QJsonArray reasons;
        auto sorted = pauseReasons.values();
        sorted.sort();
        for (const auto &reason : sorted) reasons.append(reason);
        emitEvent({{"event", "status"}, {"output", target->name()},
            {"ready", ready}, {"playing", player.playbackState() == QMediaPlayer::PlayingState},
            {"pause_reasons", reasons}, {"position_ms", player.position()},
            {"duration_ms", player.duration()}, {"frames", qint64(frames)}});
    };
    QTimer startupTimeout;
    startupTimeout.setSingleShot(true);
    QObject::connect(&startupTimeout, &QTimer::timeout, &app, [&] {
        fail("No frame presented within 15 seconds"); app.exit(3);
    });
    QObject::connect(&player, &QMediaPlayer::errorOccurred, &app,
        [&](QMediaPlayer::Error, const QString &message) { fail(message); app.exit(3); });
    QObject::connect(sink, &QVideoSink::videoFrameChanged, &app, [&](const QVideoFrame &frame) {
        if (!frame.isValid()) return;
        ++frames;
        if (!firstFrame) {
            firstFrame = true;
            if (!pauseReasons.isEmpty()) player.pause();
            view.show();
        }
    });
    QObject::connect(&view, &QQuickWindow::frameSwapped, &app, [&] {
        if (firstFrame && !ready) {
            ready = true;
            startupTimeout.stop();
            emitEvent({{"event", "ready"}, {"output", target->name()}});
            status();
        }
    });
    QObject::connect(&app, &QGuiApplication::screenRemoved, &app, [&](QScreen *screen) {
        if (screen == target) {
            emitEvent({{"event", "output_removed"}});
            app.quit();
        }
    });

    QByteArray input;
    QSocketNotifier notifier(STDIN_FILENO, QSocketNotifier::Read);
    QObject::connect(&notifier, &QSocketNotifier::activated, &app, [&] {
        char buffer[4096];
        const auto size = ::read(STDIN_FILENO, buffer, sizeof buffer);
        if (size == 0) { notifier.setEnabled(false); app.quit(); return; }
        if (size < 0) {
            if (errno != EINTR && errno != EAGAIN) app.exit(4);
            return;
        }
        input.append(buffer, size);
        if (input.size() > 65536) { fail("Command buffer exceeded 64 KiB"); app.exit(4); return; }
        qsizetype newline;
        while ((newline = input.indexOf('\n')) >= 0) {
            const auto line = input.left(newline);
            input.remove(0, newline + 1);
            QJsonParseError error;
            const auto document = QJsonDocument::fromJson(line, &error);
            if (error.error != QJsonParseError::NoError || !document.isObject()) {
                fail("Expected a JSON object"); continue;
            }
            const auto command = document.object();
            if (command.value("version").toInt(-1) != 1) { fail("Unsupported protocol version"); continue; }
            const auto name = command.value("command").toString();
            if (name == "quit") { app.quit(); return; }
            if (name == "status") { status(); continue; }
            if (name != "pause" && name != "resume") { fail("Unknown command"); continue; }
            const QString reason = command.value("reason").toString();
            if (!allowed.contains(reason)) { fail("Unknown pause reason"); continue; }
            if (!ready) { fail("Wait for ready before controlling playback"); continue; }
            if (name == "pause") pauseReasons.insert(reason);
            else pauseReasons.remove(reason);
            if (pauseReasons.isEmpty()) player.play();
            else player.pause();
            status();
        }
    });
    player.setSource(QUrl::fromLocalFile(file.absoluteFilePath()));
    startupTimeout.start(15000);
    player.play();
    const int result = app.exec();
    player.stop();
    emitEvent({{"event", "stopped"}});
    return result;
}
