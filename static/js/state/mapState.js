(function attachMapState(globalObj) {
  const ns = (globalObj.SmartRouteModules = globalObj.SmartRouteModules || {});
  ns.state = ns.state || {};

  ns.state.createMapState = function createMapState() {
    return {
      activeBusId: null,
      hasFittedBounds: false,
      visibleBusIds: [],
    };
  };
})(window);

