import QtQuick
import QtMultimedia

Rectangle {
    width: 960
    height: 540
    color: "black"
    VideoOutput {
        objectName: "video"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
        endOfStreamPolicy: VideoOutput.KeepLastFrame
    }
}
