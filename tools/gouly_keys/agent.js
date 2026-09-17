// Frida agent: report Tuya/ThingClips device credentials as the Gouly app loads them.
// Only device metadata is read; nothing about the user's account is captured.
'use strict';

const DEVICE_CLASSES = [
  'com.thingclips.smart.sdk.bean.DeviceBean',
  'com.thingclips.smart.interior.device.bean.DeviceRespBean',
];
const reported = {};
let busy = false;

function read(bean, getter) {
  try {
    const method = bean[getter];
    if (!method) return null;
    const value = method.call(bean);
    return value === null || value === undefined ? null : String(value);
  } catch (e) {
    return null;
  }
}

function report(bean) {
  if (busy) return; // getters below re-enter the hooked getLocalKey
  busy = true;
  try {
    const device = {
      devId: read(bean, 'getDevId'),
      localKey: read(bean, 'getLocalKey'),
      name: read(bean, 'getName'),
      productId: read(bean, 'getProductId'),
      version: read(bean, 'getPv'),
      mac: read(bean, 'getMac'),
    };
    if (!device.devId || !device.localKey) return;
    const signature = JSON.stringify(device);
    if (reported[device.devId] === signature) return;
    reported[device.devId] = signature;
    send({ type: 'gouly-device', device: device });
  } finally {
    busy = false;
  }
}

Java.perform(function () {
  DEVICE_CLASSES.forEach(function (name) {
    let cls;
    try {
      cls = Java.use(name);
    } catch (e) {
      return;
    }
    ['setLocalKey', 'getLocalKey'].forEach(function (method) {
      if (!cls[method]) return;
      cls[method].overloads.forEach(function (overload) {
        overload.implementation = function () {
          const result = overload.apply(this, arguments);
          report(this);
          return result;
        };
      });
    });
  });

  // Also look for device objects already in memory (e.g. loaded from the app's cache).
  setInterval(function () {
    Java.perform(function () {
      DEVICE_CLASSES.forEach(function (name) {
        try {
          Java.choose(name, { onMatch: report, onComplete: function () {} });
        } catch (e) {}
      });
    });
  }, 3000);

  send({ type: 'gouly-ready' });
});
