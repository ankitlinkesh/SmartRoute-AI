from typing import Dict, List


def nearest_neighbor_route_by_time(
    stop_ids: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
) -> List[str]:
    """Order stops by nearest-neighbor on driving time and end at college."""
    if not stop_ids:
        return []

    remaining = set(stop_ids)
    first_stop = max(
        remaining,
        key=lambda sid: matrix[index_map[sid]][index_map[college_id]]["travel_seconds"],
    )

    ordered = [first_stop]
    remaining.remove(first_stop)
    current = first_stop

    while remaining:
        next_stop = min(
            remaining,
            key=lambda sid: matrix[index_map[current]][index_map[sid]]["travel_seconds"],
        )
        ordered.append(next_stop)
        remaining.remove(next_stop)
        current = next_stop

    return ordered


def optimize_stop_order_with_ortools(
    stop_ids: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
    ortools_available: bool,
    pywrapcp,
    routing_enums_pb2,
) -> List[str]:
    """Optimize stop sequence via OR-Tools; fallback to nearest-neighbor when unavailable."""
    if len(stop_ids) <= 2 or not ortools_available:
        return nearest_neighbor_route_by_time(stop_ids, matrix, index_map, college_id)

    n = len(stop_ids)
    tsp_matrix = [[0 for _ in range(n)] for _ in range(n)]
    for i, sid_i in enumerate(stop_ids):
        for j, sid_j in enumerate(stop_ids):
            if i == j:
                tsp_matrix[i][j] = 0
            else:
                tsp_matrix[i][j] = int(
                    max(1, matrix[index_map[sid_i]][index_map[sid_j]]["travel_seconds"])
                )

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return tsp_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.time_limit.FromSeconds(2)

    solution = routing.SolveWithParameters(search_parameters)
    if solution is None:
        return nearest_neighbor_route_by_time(stop_ids, matrix, index_map, college_id)

    cycle_order_idx: List[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        cycle_order_idx.append(node)
        index = solution.Value(routing.NextVar(index))

    ordered_cycle = [stop_ids[idx] for idx in cycle_order_idx if 0 <= idx < len(stop_ids)]
    if not ordered_cycle:
        return nearest_neighbor_route_by_time(stop_ids, matrix, index_map, college_id)

    def path_cost(path: List[str]) -> float:
        if not path:
            return 0.0
        cost = 0.0
        for i in range(len(path) - 1):
            cost += float(matrix[index_map[path[i]]][index_map[path[i + 1]]]["travel_seconds"])
        cost += float(matrix[index_map[path[-1]]][index_map[college_id]]["travel_seconds"])
        return cost

    best_path = ordered_cycle[:]
    best_cost = float("inf")
    for direction in (ordered_cycle, list(reversed(ordered_cycle))):
        for shift in range(len(direction)):
            candidate = direction[shift:] + direction[:shift]
            candidate_cost = path_cost(candidate)
            if candidate_cost < best_cost:
                best_cost = candidate_cost
                best_path = candidate

    return best_path


def estimate_route_shape_cost(
    path: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
    location_by_id: Dict[str, Dict],
    haversine_km,
    college_lat: float,
    college_lon: float,
) -> float:
    """Directional shape-aware cost: travel + backtrack/lateral/reversal penalties."""
    if not path:
        return 0.0
    cost = 0.0
    campus_distances = []
    for sid in path:
        loc = location_by_id[sid]
        campus_distances.append(
            haversine_km(float(loc["lat"]), float(loc["lon"]), college_lat, college_lon)
        )

    for i in range(len(path) - 1):
        a = path[i]
        b = path[i + 1]
        leg = float(matrix[index_map[a]][index_map[b]]["travel_seconds"])
        cost += leg
        inward_delta = campus_distances[i] - campus_distances[i + 1]
        if inward_delta < -0.1:
            cost += 220.0
        lateral_jump_proxy = max(0.0, leg - (max(20.0, abs(inward_delta) * 160.0)))
        cost += lateral_jump_proxy * 0.15
        if i >= 1:
            prev_delta = campus_distances[i - 1] - campus_distances[i]
            if prev_delta * inward_delta < 0:
                cost += 120.0
    cost += float(matrix[index_map[path[-1]]][index_map[college_id]]["travel_seconds"])
    return cost


def refine_stop_order_directional(
    path: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
    location_by_id: Dict[str, Dict],
    haversine_km,
    college_lat: float,
    college_lon: float,
    route_shape_2opt_max_passes: int,
    route_shape_2opt_max_swaps: int,
) -> List[str]:
    """Bounded deterministic 2-opt style smoothing for inward directional continuity."""
    if len(path) < 4:
        return path

    best = path[:]
    best_cost = estimate_route_shape_cost(
        best,
        matrix,
        index_map,
        college_id,
        location_by_id,
        haversine_km,
        college_lat,
        college_lon,
    )
    swaps = 0
    for _ in range(max(1, route_shape_2opt_max_passes)):
        improved = False
        for i in range(0, len(best) - 2):
            for j in range(i + 2, len(best)):
                if swaps >= max(8, route_shape_2opt_max_swaps):
                    return best
                candidate = best[:i] + list(reversed(best[i:j])) + best[j:]
                candidate_cost = estimate_route_shape_cost(
                    candidate,
                    matrix,
                    index_map,
                    college_id,
                    location_by_id,
                    haversine_km,
                    college_lat,
                    college_lon,
                )
                swaps += 1
                if candidate_cost + 1e-6 < best_cost:
                    best = candidate
                    best_cost = candidate_cost
                    improved = True
        if not improved:
            break
    return best
