(function attachStopLayerManager(globalObj) {
  const ns = (globalObj.SmartRouteModules = globalObj.SmartRouteModules || {});
  ns.map = ns.map || {};

  ns.map.createStopLayerManager = function createStopLayerManager(leafletMap) {
    const stopLayer = L.layerGroup().addTo(leafletMap);
    const focusStopLayer = L.layerGroup().addTo(leafletMap);

    return {
      clear() {
        stopLayer.clearLayers();
        focusStopLayer.clearLayers();
      },
      addStop(marker, focused) {
        marker.addTo(focused ? focusStopLayer : stopLayer);
      },
      getLayers() {
        return { stopLayer, focusStopLayer };
      },
    };
  };
})(window);

