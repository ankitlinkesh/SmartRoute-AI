(function attachSmartRouteStore(globalObj) {
  const ns = (globalObj.SmartRouteModules = globalObj.SmartRouteModules || {});
  ns.state = ns.state || {};

  ns.state.createStore = function createStore(initialState) {
    let state = Object.assign({}, initialState || {});
    return {
      getState() {
        return state;
      },
      setState(nextState) {
        state = Object.assign({}, state, nextState || {});
        return state;
      },
    };
  };
})(window);

