(function attachRouteLayerManager(globalObj) {
  const ns = (globalObj.SmartRouteModules = globalObj.SmartRouteModules || {});
  ns.map = ns.map || {};

  ns.map.createRouteLayerManager = function createRouteLayerManager(leafletMap) {
    const routeLayer = L.layerGroup().addTo(leafletMap);
    const focusLayer = L.layerGroup().addTo(leafletMap);

    return {
      clear() {
        routeLayer.clearLayers();
        focusLayer.clearLayers();
      },
      addRoute(polyline, focused) {
        polyline.addTo(focused ? focusLayer : routeLayer);
      },
      getLayers() {
        return { routeLayer, focusLayer };
      },
    };
  };
})(window);

