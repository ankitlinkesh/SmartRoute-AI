document.addEventListener("DOMContentLoaded", () => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const hasGSAP = Boolean(window.gsap && window.ScrollTrigger);
    const body = document.body;

    if (hasGSAP) {
        window.gsap.registerPlugin(window.ScrollTrigger);
    }

    initSmoothAnchorLinks();
    initNavbarMotion();
    initInteractiveCards(reduceMotion);

    if (body.classList.contains("landing-page")) {
        initLandingPage({ reduceMotion, hasGSAP });
    }

    if (body.classList.contains("results-page-body")) {
        initResultsPage({ reduceMotion, hasGSAP });
    }

    if (body.classList.contains("upload-page-body")) {
        initUploadPage();
    }
});

function initUploadPage() {
    const form = document.getElementById("upload-form");
    const overlay = document.getElementById("uploadLoadingOverlay");
    const submitButton = document.getElementById("generateBtn");
    if (!form || !overlay) {
        return;
    }

    const activateOverlay = () => {
        overlay.classList.add("is-active");
        overlay.setAttribute("aria-hidden", "false");
        document.body.classList.add("upload-loading-lock");
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.classList.add("is-loading");
        }
    };

    const deactivateOverlay = () => {
        overlay.classList.remove("is-active");
        overlay.setAttribute("aria-hidden", "true");
        document.body.classList.remove("upload-loading-lock");
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.classList.remove("is-loading");
        }
    };

    form.addEventListener("submit", () => {
        activateOverlay();
    });

    window.addEventListener("pageshow", () => {
        deactivateOverlay();
    });
}

function initLandingPage({ reduceMotion, hasGSAP }) {
    initParticles();
    initCharts();

    if (!reduceMotion && hasGSAP) {
        initRevealAnimations(".landing-page .motion-reveal");
        initScrollParallax();
        initHeroMotion();
        initPinnedStorySections();
        initRouteLineFlow();
        initCounters("[data-counter]", true);
    } else {
        revealWithoutMotion(".landing-page .motion-reveal");
        initCounters("[data-counter]", false);
    }
}

function initResultsPage({ reduceMotion, hasGSAP }) {
    if (!reduceMotion && hasGSAP) {
        initRevealAnimations(".results-page-body .motion-reveal");
        initResultsCardStagger();
        initMetricsCountUp();
    } else {
        revealWithoutMotion(".results-page-body .motion-reveal");
    }

    if (window.SMARTROUTE_RESULTS && Array.isArray(window.SMARTROUTE_RESULTS.buses)) {
        initManualRouteEditor(window.SMARTROUTE_RESULTS);
        initProjectSaveAndSimulation(window.SMARTROUTE_RESULTS);
    }
}

function normalizeConstraintValue(value, fallbackValue = null) {
    if (value === null || value === undefined) {
        return null;
    }
    if (typeof value === "string") {
        const token = value.trim().toLowerCase();
        if (!token || token === "none" || token === "null" || token === "- no constraints -") {
            return null;
        }
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        return fallbackValue;
    }
    return Math.round(parsed);
}

function initProjectSaveAndSimulation(resultsData) {
    const saveBtn = document.getElementById("saveProjectBtn");
    const panel = document.getElementById("saveProjectInlinePanel");
    const confirmBtn = document.getElementById("confirmSaveProjectBtn");
    const overwriteBtn = document.getElementById("overwriteSaveProjectBtn");
    const cancelBtn = document.getElementById("cancelSaveProjectBtn");
    const input = document.getElementById("projectNameInput");
    const errorNode = document.getElementById("saveProjectError");
    const runSimulationBtn = document.getElementById("runSimulationBtn");
    const simOccupancy = document.getElementById("simOccupancySlider");
    const simOccupancyValue = document.getElementById("simOccupancyValue");
    const simDisableBus = document.getElementById("simDisableBusSelect");
    const simOverflowToggle = document.getElementById("simOverflowToggle");
    const simOverflowLimit = document.getElementById("simOverflowLimit");
    const simulationWarnings = document.getElementById("simulationWarnings");
    const simOverflowHintId = "simOverflowHint";
    let conflictProjectName = "";

    const openPanel = () => {
        if (!panel) return;
        panel.hidden = false;
        if (overwriteBtn) overwriteBtn.hidden = true;
        if (errorNode) errorNode.textContent = "";
        conflictProjectName = "";
        if (confirmBtn) confirmBtn.textContent = "Save";
        if (input && resultsData.projectMeta && resultsData.projectMeta.project_name) {
            input.value = resultsData.projectMeta.project_name;
        }
        if (input) input.focus();
    };
    const closePanel = () => {
        if (!panel) return;
        panel.hidden = true;
    };

    async function saveProject(overwrite) {
        if (!input || !errorNode) return;
        const projectName = String(input.value || "").trim();
        if (!projectName) {
            errorNode.textContent = "Project Name is required.";
            return;
        }
        const editorApi = window.SMARTROUTE_EDITOR_API;
        const editorSnapshot = editorApi && typeof editorApi.exportState === "function"
            ? editorApi.exportState()
            : null;

        const metrics = {
            ...(resultsData.metrics || {}),
            overload_percent: Number((document.getElementById("ctrlOverloadPercentage")?.textContent || "0").replace("%", "")) || 0,
            overflow_passengers: Number(document.getElementById("ctrlTotalOverflowPassengers")?.textContent || "0") || 0,
            unused_capacity: Number(document.getElementById("ctrlUnusedCapacity")?.textContent || "0") || 0,
            total_students: Array.isArray(resultsData.assignments) ? resultsData.assignments.length : 0,
            required_buses_without_overflow: Number(resultsData.metrics?.required_buses_without_overflow || 0),
            required_buses_with_current_capacity: Number(resultsData.metrics?.required_buses_with_current_capacity || 0),
            bus_reduction_from_overflow: Number(resultsData.metrics?.bus_reduction_from_overflow || 0),
            quality_metrics: resultsData.metrics?.quality_metrics || { per_bus: [], global: {} },
        };
        const configState = editorApi && typeof editorApi.getSettings === "function"
            ? editorApi.getSettings()
            : {
                occupancy_percent: Number(simOccupancy?.value || 90),
                overflow_enabled: Boolean(simOverflowToggle?.checked),
                overflow_limit: Number(simOverflowLimit?.value || 0),
                bus_capacity: Number(resultsData.configuredBusCapacity || 0),
                per_bus_actual_capacities: resultsData.configuredPerBusCapacities || {},
                arrival_time: String(resultsData.configuredArrivalTime || "08:30"),
                max_ride_duration_minutes: normalizeConstraintValue(resultsData.configuredMaxRideDuration, 120),
                stop_dwell_seconds: normalizeConstraintValue(resultsData.configuredStopDwellSeconds, 20),
                routing_policy: String(resultsData.configuredRoutingPolicy || "balanced"),
            };

        const shouldOverwrite = Boolean(
            overwrite || (overwriteBtn && !overwriteBtn.hidden && conflictProjectName === projectName)
        );
        const payload = {
            project_name: projectName,
            overwrite: shouldOverwrite,
            merged_students: resultsData.mergedStudents || [],
            assignments: editorSnapshot?.assignments || resultsData.assignments || [],
            buses: editorSnapshot?.buses || resultsData.buses || [],
            map_data: resultsData.mapData || {},
            upload_summary: resultsData.uploadSummary || {},
            metrics,
            config_state: configState,
            simulation_state: editorSnapshot?.simulationState || {},
            manual_plan_state: editorSnapshot?.manualState || {},
            warnings: [],
        };

        const response = await fetch("/api/projects/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const responsePayload = await response.json();
        if (!response.ok) {
            if (responsePayload.code === "PROJECT_EXISTS" && overwriteBtn) {
                overwriteBtn.hidden = false;
                errorNode.textContent = "Project already exists.";
                conflictProjectName = projectName;
                if (confirmBtn) confirmBtn.textContent = "Save As New Name";
                return;
            }
            errorNode.textContent = responsePayload.message || "Project save failed.";
            return;
        }
        closePanel();
    }

    if (saveBtn) {
        saveBtn.addEventListener("click", () => {
            if (panel && !panel.hidden) {
                closePanel();
            } else {
                openPanel();
            }
        });
    }
    if (confirmBtn) confirmBtn.addEventListener("click", () => saveProject(false));
    if (overwriteBtn) overwriteBtn.addEventListener("click", () => saveProject(true));
    if (cancelBtn) cancelBtn.addEventListener("click", closePanel);
    if (input) {
        input.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") {
                return;
            }
            event.preventDefault();
            const useOverwrite = Boolean(overwriteBtn && !overwriteBtn.hidden && conflictProjectName === String(input.value || "").trim());
            saveProject(useOverwrite);
        });
    }
    if (simOccupancy && simOccupancyValue) {
        simOccupancy.addEventListener("input", () => {
            simOccupancyValue.textContent = `${simOccupancy.value}%`;
        });
    }

    const ensureSimHintNode = () => {
        if (!simOverflowLimit) return null;
        let hint = document.getElementById(simOverflowHintId);
        if (!hint) {
            hint = document.createElement("p");
            hint.id = simOverflowHintId;
            hint.className = "hint";
            hint.style.color = "#fcd34d";
            simOverflowLimit.insertAdjacentElement("afterend", hint);
        }
        return hint;
    };

    const refreshSimOverflowHint = () => {
        if (!simOverflowLimit || !simOverflowToggle) return;
        const hint = ensureSimHintNode();
        if (!hint) return;
        const limit = Number(simOverflowLimit.value || 0);
        if (limit > 0 && !simOverflowToggle.checked) {
            hint.textContent = "Overflow limit is ignored until Overflow is ON.";
        } else {
            hint.textContent = "";
        }
    };

    if (simOverflowLimit && simOverflowToggle) {
        simOverflowLimit.addEventListener("input", () => {
            const limit = Number(simOverflowLimit.value || 0);
            if (limit > 0 && !simOverflowToggle.checked) {
                simOverflowToggle.checked = true;
            }
            refreshSimOverflowHint();
        });
        simOverflowToggle.addEventListener("change", refreshSimOverflowHint);
        refreshSimOverflowHint();
    }

    if (runSimulationBtn) {
        runSimulationBtn.addEventListener("click", async () => {
            if (simulationWarnings) simulationWarnings.textContent = "Running simulation...";
            runSimulationBtn.disabled = true;
            const editorApi = window.SMARTROUTE_EDITOR_API;
            const snapshot = editorApi && typeof editorApi.exportState === "function"
                ? editorApi.exportState()
                : { buses: resultsData.buses || [], assignments: resultsData.assignments || [] };
            const disabled = simDisableBus && simDisableBus.value ? [Number(simDisableBus.value)] : [];

            try {
                const response = await fetch("/api/simulate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        routes: snapshot.buses || [],
                        assignments: snapshot.assignments || [],
                        occupancy_percent: Number(simOccupancy?.value || 90),
                        overflow_enabled: Boolean(simOverflowToggle?.checked),
                        overflow_limit: Number(simOverflowLimit?.value || 0),
                        disabled_buses: disabled,
                        bus_capacity: Number(resultsData.configuredBusCapacity || 0),
                        per_bus_actual_capacities: resultsData.configuredPerBusCapacities || {},
                        max_ride_duration_minutes: normalizeConstraintValue(resultsData.configuredMaxRideDuration, 120),
                        stop_dwell_seconds: normalizeConstraintValue(resultsData.configuredStopDwellSeconds, 20),
                routing_policy: String(resultsData.configuredRoutingPolicy || "balanced"),
                    }),
                });
                const body = await response.json();
                if (!response.ok || !body.ok) {
                    if (simulationWarnings) simulationWarnings.textContent = body.message || "Simulation failed.";
                    return;
                }

                const sim = body.result.metrics || {};
                const simulatedRoutes = (snapshot.buses || []).filter((bus) => !disabled.includes(Number(bus.bus_number)));
                const simulationSettings = {
                    occupancyPercent: Number(simOccupancy?.value || 90),
                    overflowEnabled: Boolean(simOverflowToggle?.checked),
                    overflowLimitPerBus: Number(simOverflowLimit?.value || 0),
                };
                const simulatedHealth = editorApi && typeof editorApi.getHealthSummary === "function"
                    ? editorApi.getHealthSummary(simulatedRoutes, simulationSettings)
                    : { healthy: "-", caution: "-", severe: "-" };
                const setText = (id, value) => {
                    const node = document.getElementById(id);
                    if (node) node.textContent = String(value);
                };
                setText("simResultBuses", sim.buses_used ?? "-");
                setText("simResultAvgTime", sim.avg_travel_time ?? "-");
                setText("simResultOverflow", sim.overflow_passengers ?? "-");
                setText("simResultUnassigned", sim.unassigned_students ?? "-");
                setText("simResultDistance", sim.avg_distance ?? "-");
                setText("simResultHealthy", simulatedHealth.healthy);
                setText("simResultCaution", simulatedHealth.caution);
                setText("simResultSevere", simulatedHealth.severe);

                if (simulationWarnings) {
                    const healthSummary = `Health summary: ${simulatedHealth.healthy} healthy, ${simulatedHealth.caution} caution, ${simulatedHealth.severe} severe.`;
                    simulationWarnings.textContent = [...(body.result.warnings || []), healthSummary].join(" ") || "Simulation completed.";
                }
            } catch (error) {
                if (simulationWarnings) simulationWarnings.textContent = "Simulation failed. Please check the route data and try again.";
            } finally {
                runSimulationBtn.disabled = false;
            }
        });
    }
}

function initParticles() {
    const particleContainer = document.getElementById("particles");
    if (!particleContainer) {
        return;
    }

    const particleCount = 55;
    for (let i = 0; i < particleCount; i += 1) {
        const particle = document.createElement("span");
        particle.className = "particle";
        particle.style.left = `${Math.random() * 100}%`;
        particle.style.top = `${70 + Math.random() * 30}%`;
        particle.style.animationDuration = `${6 + Math.random() * 8}s`;
        particle.style.animationDelay = `${Math.random() * 8}s`;
        particleContainer.appendChild(particle);
    }
}

function initSmoothAnchorLinks() {
    document.querySelectorAll("a.nav-link").forEach((link) => {
        link.addEventListener("click", (event) => {
            const href = link.getAttribute("href");
            if (!href || !href.startsWith("#")) {
                return;
            }

            const target = document.querySelector(href);
            if (!target) {
                return;
            }

            event.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });
}

function initNavbarMotion() {
    const navbar = document.getElementById("siteNavbar");
    if (!navbar) {
        return;
    }

    const updateNavbarState = () => {
        if (window.scrollY > 22) {
            navbar.classList.add("nav-scrolled");
        } else {
            navbar.classList.remove("nav-scrolled");
        }
    };

    updateNavbarState();
    window.addEventListener("scroll", updateNavbarState, { passive: true });
}

function initRevealAnimations(selector) {
    const targets = document.querySelectorAll(selector);
    targets.forEach((element, index) => {
        const isScale = element.classList.contains("reveal-scale");
        const isBlur = element.classList.contains("reveal-blur");
        const fromVars = {
            opacity: 0,
            y: isScale ? 26 : 34,
            scale: isScale ? 0.96 : 1,
            filter: isBlur ? "blur(12px)" : "blur(0px)",
            force3D: true,
        };

        window.gsap.from(element, {
            ...fromVars,
            duration: 0.85,
            ease: "power3.out",
            delay: Math.min(index * 0.03, 0.24),
            clearProps: "opacity,transform,filter",
            scrollTrigger: {
                trigger: element,
                start: "top 86%",
                once: true,
            },
        });
    });
}

function revealWithoutMotion(selector) {
    document.querySelectorAll(selector).forEach((element) => {
        element.style.opacity = "1";
        element.style.transform = "none";
        element.style.filter = "none";
    });
}

function initScrollParallax() {
    window.gsap.utils.toArray(".landing-page .section-title").forEach((heading) => {
        window.gsap.to(heading, {
            y: -26,
            ease: "none",
            force3D: true,
            scrollTrigger: {
                trigger: heading,
                start: "top bottom",
                end: "bottom top",
                scrub: true,
            },
        });
    });

    window.gsap.utils.toArray(".landing-page .glass-card, .landing-page .feature-card, .landing-page .demo-step").forEach((card) => {
        window.gsap.to(card, {
            y: -16,
            ease: "none",
            force3D: true,
            scrollTrigger: {
                trigger: card,
                start: "top 95%",
                end: "bottom top",
                scrub: true,
            },
        });
    });

    const bgGrid = document.getElementById("bgGrid");
    const bgNebula = document.getElementById("bgNebula");
    const layers = [
        { element: bgGrid, speed: 0.06 },
        { element: bgNebula, speed: 0.03 },
    ];

    let ticking = false;
    const updateLayers = () => {
        const y = window.scrollY;
        layers.forEach((layer) => {
            if (!layer.element) {
                return;
            }
            layer.element.style.transform = `translate3d(0, ${y * layer.speed}px, 0)`;
        });
        ticking = false;
    };

    window.addEventListener("scroll", () => {
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(updateLayers);
        }
    }, { passive: true });
}

function initHeroMotion() {
    const heroVisual = document.querySelector(".hero-visual.tilt-surface");
    if (!heroVisual) {
        return;
    }

    window.gsap.to(".floating-card", {
        y: -10,
        repeat: -1,
        yoyo: true,
        duration: 2.2,
        stagger: 0.28,
        ease: "sine.inOut",
    });

    window.gsap.to(".route-lines", {
        opacity: 0.82,
        repeat: -1,
        yoyo: true,
        duration: 2.8,
        ease: "sine.inOut",
    });

    window.gsap.to(".bg-nebula", {
        opacity: 0.92,
        repeat: -1,
        yoyo: true,
        duration: 4.4,
        ease: "sine.inOut",
    });

    let pending = false;
    let nextX = 0;
    let nextY = 0;
    const applyTilt = () => {
        window.gsap.to(heroVisual, {
            rotateX: nextY,
            rotateY: nextX,
            transformPerspective: 1000,
            transformOrigin: "center center",
            duration: 0.28,
            ease: "power2.out",
            overwrite: true,
        });
        pending = false;
    };

    heroVisual.addEventListener("mousemove", (event) => {
        const rect = heroVisual.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width;
        const y = (event.clientY - rect.top) / rect.height;
        nextX = (x - 0.5) * 8;
        nextY = (0.5 - y) * 7;
        if (!pending) {
            pending = true;
            requestAnimationFrame(applyTilt);
        }
    });

    heroVisual.addEventListener("mouseleave", () => {
        window.gsap.to(heroVisual, {
            rotateX: 0,
            rotateY: 0,
            duration: 0.35,
            ease: "power2.out",
        });
    });
}

function initPinnedStorySections() {
    if (!window.matchMedia("(min-width: 1024px)").matches) {
        return;
    }

    window.gsap.utils.toArray(".story-pin").forEach((section) => {
        window.ScrollTrigger.create({
            trigger: section,
            start: "top 92px",
            end: "+=220",
            pin: true,
            pinSpacing: true,
            scrub: 0.4,
            anticipatePin: 1,
        });
    });
}

function initRouteLineFlow() {
    window.gsap.to(".route-line", {
        strokeDashoffset: -300,
        duration: 6,
        repeat: -1,
        ease: "none",
        stagger: 0.42,
    });

    window.gsap.to(".node", {
        scale: 1.16,
        repeat: -1,
        yoyo: true,
        transformOrigin: "center center",
        duration: 1.2,
        stagger: 0.1,
        ease: "sine.inOut",
    });
}

function initInteractiveCards(reduceMotion) {
    const cards = document.querySelectorAll(".interactive-card");
    cards.forEach((card) => {
        card.classList.add("card-tilt");
        if (reduceMotion) {
            return;
        }

        let rafId = 0;
        card.addEventListener("mousemove", (event) => {
            if (rafId) {
                return;
            }
            rafId = requestAnimationFrame(() => {
                const rect = card.getBoundingClientRect();
                const x = (event.clientX - rect.left) / rect.width;
                const y = (event.clientY - rect.top) / rect.height;
                const rotateY = (x - 0.5) * 6;
                const rotateX = (0.5 - y) * 5;
                card.style.transform = `translate3d(0, -4px, 0) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
                rafId = 0;
            });
        });

        card.addEventListener("mouseleave", () => {
            card.style.transform = "";
        });
    });
}

function initCounters(selector, useScrollTrigger) {
    const counters = document.querySelectorAll(selector);
    counters.forEach((counter) => {
        const target = Number(counter.getAttribute("data-counter") || "0");
        if (!Number.isFinite(target)) {
            return;
        }

        const run = () => animateCount(counter, target, 1300, (value) => value.toLocaleString());
        if (useScrollTrigger && window.ScrollTrigger) {
            window.ScrollTrigger.create({
                trigger: counter,
                start: "top 88%",
                once: true,
                onEnter: run,
            });
        } else {
            run();
        }
    });
}

function initMetricsCountUp() {
    const metrics = document.querySelectorAll(".results-page-body .metric-value");
    metrics.forEach((metric) => {
        const rawText = metric.textContent || "";
        const match = rawText.match(/-?\d+(\.\d+)?/);
        if (!match || !window.ScrollTrigger) {
            return;
        }

        const numericValue = Number(match[0]);
        const suffix = rawText.replace(match[0], "").trim();
        window.ScrollTrigger.create({
            trigger: metric,
            start: "top 88%",
            once: true,
            onEnter: () => {
                animateCount(
                    metric,
                    numericValue,
                    1000,
                    (value) => `${numericValue % 1 === 0 ? Math.round(value) : value.toFixed(1)}${suffix ? ` ${suffix}` : ""}`
                );
            },
        });
    });
}

function initResultsCardStagger() {
    if (!window.gsap || !window.ScrollTrigger) {
        return;
    }
    const cards = window.gsap.utils.toArray(".results-page-body .route-card");
    if (!cards.length) {
        return;
    }

    window.gsap.from(cards, {
        opacity: 0,
        y: 22,
        duration: 0.55,
        stagger: 0.06,
        ease: "power2.out",
        scrollTrigger: {
            trigger: ".details-pane",
            start: "top 86%",
            once: true,
        },
    });
}

function animateCount(element, target, duration, formatter) {
    const start = performance.now();
    const from = 0;

    const tick = (now) => {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const value = from + (target - from) * eased;
        element.textContent = formatter(value);
        if (progress < 1) {
            requestAnimationFrame(tick);
        }
    };

    requestAnimationFrame(tick);
}

function initCharts() {
    const efficiencyCanvas = document.getElementById("efficiencyChart");
    if (efficiencyCanvas && window.Chart) {
        new window.Chart(efficiencyCanvas, {
            type: "line",
            data: {
                labels: ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"],
                datasets: [{
                    label: "Route Efficiency %",
                    data: [62, 70, 78, 85, 91],
                    borderColor: "#22d3ee",
                    backgroundColor: "rgba(34,211,238,0.2)",
                    tension: 0.35,
                    fill: true,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: "#dbeafe" } },
                },
                scales: {
                    x: { ticks: { color: "#9fb2d1" }, grid: { color: "rgba(148,163,184,0.15)" } },
                    y: { ticks: { color: "#9fb2d1" }, grid: { color: "rgba(148,163,184,0.15)" } },
                },
            },
        });
    }

    const utilizationCanvas = document.getElementById("utilizationChart");
    if (utilizationCanvas && window.Chart) {
        new window.Chart(utilizationCanvas, {
            type: "bar",
            data: {
                labels: ["Distance Saved", "Commute Reduced", "Fuel Saved", "Bus Utilization"],
                datasets: [{
                    label: "Impact",
                    data: [34, 29, 22, 88],
                    backgroundColor: ["#22d3ee", "#818cf8", "#34d399", "#f59e0b"],
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: "#dbeafe" } },
                },
                scales: {
                    x: { ticks: { color: "#9fb2d1" }, grid: { color: "rgba(148,163,184,0.15)" } },
                    y: { ticks: { color: "#9fb2d1" }, grid: { color: "rgba(148,163,184,0.15)" } },
                },
            },
        });
    }
}

function initManualRouteEditor(resultsData) {
    if (!resultsData.buses.length) {
        return;
    }

    const palette = [
        "#2563eb", "#dc2626", "#0f766e", "#9333ea", "#d97706", "#0284c7", "#16a34a", "#be123c",
        "#7c3aed", "#0891b2", "#ea580c", "#65a30d", "#c026d3", "#1d4ed8", "#b45309", "#334155",
        "#ef4444", "#14b8a6", "#8b5cf6", "#f59e0b", "#22c55e", "#e11d48", "#06b6d4", "#84cc16",
        "#f97316", "#6366f1", "#10b981", "#a855f7", "#3b82f6", "#f43f5e", "#2dd4bf", "#4f46e5",
        "#ca8a04", "#059669", "#7e22ce", "#0ea5e9", "#c2410c", "#4338ca", "#15803d", "#9f1239"
    ];

    const storageKey = "smartroute_manual_plan_v1";
    const mapData = resultsData.mapData || {};
    const college = mapData.college || { name: "College", lat: 0, lon: 0 };
    const busCapacity = Number(resultsData.configuredBusCapacity) > 0
        ? Number(resultsData.configuredBusCapacity)
        : Math.max(...resultsData.buses.map((bus) => Number(bus.total_students) || 1), 1);

    const state = createInitialEditorState(resultsData, busCapacity, college);
    if (resultsData.manualPlanState && Array.isArray(resultsData.manualPlanState.buses) && Array.isArray(resultsData.manualPlanState.students)) {
        state.buses = resultsData.manualPlanState.buses;
        state.students = resultsData.manualPlanState.students;
        if (resultsData.manualPlanState.settings) {
            state.settings = {
                ...state.settings,
                ...resultsData.manualPlanState.settings,
            };
        }
    }
    const refs = {
        modeToggleBtn: document.getElementById("modeToggleBtn"),
        undoBtn: document.getElementById("undoBtn"),
        redoBtn: document.getElementById("redoBtn"),
        savePlanBtn: document.getElementById("savePlanBtn"),
        loadPlanBtn: document.getElementById("loadPlanBtn"),
        exportJsonBtn: document.getElementById("exportJsonBtn"),
        exportCsvBtn: document.getElementById("exportCsvBtn"),
        printPdfBtn: document.getElementById("printPdfBtn"),
        routePlanFileInput: document.getElementById("routePlanFileInput"),
        addStopBtn: document.getElementById("addStopBtn"),
        newStopName: document.getElementById("newStopName"),
        newStopLat: document.getElementById("newStopLat"),
        newStopLon: document.getElementById("newStopLon"),
        newStopBus: document.getElementById("newStopBus"),
        occupancySlider: document.getElementById("occupancySlider"),
        occupancyValue: document.getElementById("occupancyValue"),
        overflowModeToggle: document.getElementById("overflowModeToggle"),
        overflowLimitInput: document.getElementById("overflowLimitInput"),
        previewActualCapacity: document.getElementById("previewActualCapacity"),
        previewPlannedOccupancy: document.getElementById("previewPlannedOccupancy"),
        previewPlannedSeats: document.getElementById("previewPlannedSeats"),
        previewOverflowAllowed: document.getElementById("previewOverflowAllowed"),
        previewMaxAllowed: document.getElementById("previewMaxAllowed"),
        overflowSafetyWarning: document.getElementById("overflowSafetyWarning"),
        overflowSuggestion: document.getElementById("overflowSuggestion"),
        assignmentsBody: document.getElementById("manualAssignmentsBody"),
        routeEditor: document.getElementById("manualRouteEditor"),
        staticBusCards: document.getElementById("staticBusCards"),
        metrics: {
            totalBuses: document.getElementById("ctrlTotalBuses"),
            overloaded: document.getElementById("ctrlOverloadedBuses"),
            unassigned: document.getElementById("ctrlUnassignedStudents"),
            locked: document.getElementById("ctrlLockedStops"),
            overrides: document.getElementById("ctrlManualOverrides"),
            totalOverflow: document.getElementById("ctrlTotalOverflowPassengers"),
            busesUsingOverflow: document.getElementById("ctrlBusesUsingOverflow"),
            overloadPercent: document.getElementById("ctrlOverloadPercentage"),
            unusedCapacity: document.getElementById("ctrlUnusedCapacity"),
            healthyRoutes: document.getElementById("ctrlHealthyRoutes"),
            cautionRoutes: document.getElementById("ctrlCautionRoutes"),
            severeRoutes: document.getElementById("ctrlSevereRoutes"),
        },
    };
    const overflowHintId = "overflowLimitHint";

    if (refs.staticBusCards) {
        refs.staticBusCards.style.display = "none";
    }

    let map = null;
    let routeLayer = null;
    let markerLayer = null;
    let focusedRouteLayer = null;
    let focusedStopLayer = null;
    let hasFittedBounds = false;
    let dragSource = null;
    let studentIndex = new Map();

    tryRestoreFromLocal();
    bindActions();
    renderAll();
    window.SMARTROUTE_EDITOR_API = {
        exportState: () => ({
            buses: state.buses,
            assignments: state.students.map((student) => {
                const stop = findStopByKey(student.stopKey);
                return {
                    student_name: student.student_name,
                    stop_name: stop ? stop.name : "",
                    stop_id: stop ? stop.stop_id : "",
                    bus_number: stop ? stop.bus_number : "",
                    pickup_time: stop ? stop.pickup_time : "",
                    source_file: student.source_file || "",
                };
            }),
            manualState: {
                buses: state.buses,
                students: state.students,
                settings: state.settings,
            },
            simulationState: {},
        }),
        getSettings: () => ({
            occupancy_percent: Number(state.settings.occupancyPercent || 90),
            overflow_enabled: Boolean(state.settings.overflowEnabled),
            overflow_limit: Number(state.settings.overflowLimitPerBus || 0),
            bus_capacity: Number(state.busCapacity || 0),
            per_bus_actual_capacities: Object.fromEntries(
                state.buses.map((bus) => [String(bus.bus_number), Math.max(1, Number(bus.actual_capacity || state.busCapacity || 1))])
            ),
            arrival_time: String(resultsData.configuredArrivalTime || "08:30"),
            max_ride_duration_minutes: normalizeConstraintValue(resultsData.configuredMaxRideDuration, 120),
            stop_dwell_seconds: normalizeConstraintValue(resultsData.configuredStopDwellSeconds, 20),
        }),
        getHealthSummary: (routesOverride, settingsOverride) => summarizeRouteHealth(
            Array.isArray(routesOverride) ? routesOverride : state.buses,
            settingsOverride || null
        ),
    };

    function bindActions() {
        if (refs.occupancySlider && refs.occupancyValue) {
            refs.occupancySlider.value = String(state.settings.occupancyPercent);
            refs.occupancyValue.textContent = `${state.settings.occupancyPercent}%`;
            refs.occupancySlider.addEventListener("input", (event) => {
                const value = Number(event.target.value);
                refs.occupancyValue.textContent = `${value}%`;
            });
            refs.occupancySlider.addEventListener("change", (event) => {
                const value = Math.max(50, Math.min(120, Number(event.target.value) || 90));
                pushHistory();
                state.settings.occupancyPercent = value;
                state.overrideActions += 1;
                renderAll();
            });
        }

        if (refs.overflowModeToggle) {
            refs.overflowModeToggle.checked = state.settings.overflowEnabled;
            refs.overflowModeToggle.addEventListener("change", (event) => {
                pushHistory();
                state.settings.overflowEnabled = Boolean(event.target.checked);
                state.overrideActions += 1;
                renderAll();
            });
        }

        if (refs.overflowLimitInput) {
            refs.overflowLimitInput.value = String(state.settings.overflowLimitPerBus);
            refs.overflowLimitInput.addEventListener("input", (event) => {
                const value = Math.max(0, Math.round(Number(event.target.value) || 0));
                if (value > 0 && refs.overflowModeToggle && !refs.overflowModeToggle.checked) {
                    refs.overflowModeToggle.checked = true;
                }
                refreshOverflowHint();
            });
            refs.overflowLimitInput.addEventListener("change", (event) => {
                const value = Math.max(0, Math.round(Number(event.target.value) || 0));
                pushHistory();
                state.settings.overflowLimitPerBus = value;
                if (value > 0) {
                    state.settings.overflowEnabled = true;
                }
                state.overrideActions += 1;
                renderAll();
            });
        }

        if (refs.modeToggleBtn) {
            refs.modeToggleBtn.addEventListener("click", () => {
                state.manualMode = !state.manualMode;
                renderAll();
            });
        }

        if (refs.undoBtn) {
            refs.undoBtn.addEventListener("click", undo);
        }

        if (refs.redoBtn) {
            refs.redoBtn.addEventListener("click", redo);
        }

        if (refs.savePlanBtn) {
            refs.savePlanBtn.addEventListener("click", savePlanFile);
        }

        if (refs.loadPlanBtn && refs.routePlanFileInput) {
            refs.loadPlanBtn.addEventListener("click", () => refs.routePlanFileInput.click());
            refs.routePlanFileInput.addEventListener("change", loadPlanFromFile);
        }

        if (refs.exportJsonBtn) {
            refs.exportJsonBtn.addEventListener("click", exportAssignmentsJson);
        }

        if (refs.exportCsvBtn) {
            refs.exportCsvBtn.addEventListener("click", exportAssignmentsCsv);
        }

        if (refs.printPdfBtn) {
            refs.printPdfBtn.addEventListener("click", () => window.print());
        }

        if (refs.addStopBtn) {
            refs.addStopBtn.addEventListener("click", () => {
                if (!state.manualMode) {
                    return;
                }
                const stopName = (refs.newStopName?.value || "").trim();
                const stopLat = Number(refs.newStopLat?.value);
                const stopLon = Number(refs.newStopLon?.value);
                const targetBus = Number(refs.newStopBus?.value);

                if (!stopName || !Number.isFinite(stopLat) || !Number.isFinite(stopLon) || !Number.isFinite(targetBus)) {
                    return;
                }

                pushHistory();
                addCustomStop(stopName, stopLat, stopLon, targetBus);
                if (refs.newStopName) refs.newStopName.value = "";
                if (refs.newStopLat) refs.newStopLat.value = "";
                if (refs.newStopLon) refs.newStopLon.value = "";
                renderAll();
            });
        }

        if (refs.assignmentsBody) {
            refs.assignmentsBody.addEventListener("change", (event) => {
                const target = event.target;
                if (!(target instanceof HTMLSelectElement)) {
                    return;
                }
                if (target.classList.contains("assignment-stop-select")) {
                    if (!state.manualMode) {
                        target.value = target.dataset.current || "";
                        return;
                    }
                    const studentId = target.dataset.studentId;
                    const newStopKey = target.value || null;
                    pushHistory();
                    reassignStudentToStop(studentId, newStopKey);
                    renderAll();
                }
            });
        }

        if (refs.routeEditor) {
            refs.routeEditor.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof HTMLElement)) {
                    return;
                }

                const lockBtn = target.closest(".lock-stop-btn");
                if (lockBtn) {
                    if (!state.manualMode) {
                        return;
                    }
                    const stopKey = lockBtn.getAttribute("data-stop-key");
                    pushHistory();
                    toggleStopLock(stopKey);
                    renderAll();
                    return;
                }

                const removeBtn = target.closest(".remove-stop-btn");
                if (removeBtn) {
                    if (!state.manualMode) {
                        return;
                    }
                    const stopKey = removeBtn.getAttribute("data-stop-key");
                    pushHistory();
                    removeStop(stopKey);
                    renderAll();
                    return;
                }

                const viewBtn = target.closest(".view-on-map-btn");
                if (viewBtn) {
                    const busNumber = Number(viewBtn.getAttribute("data-bus-number"));
                    state.activeBusId = Number.isFinite(busNumber) ? busNumber : null;
                    renderRouteEditor();
                    renderMap();
                    persistToLocal();
                    return;
                }

                const showAllBtn = target.closest(".show-all-routes-btn");
                if (showAllBtn) {
                    state.activeBusId = null;
                    renderRouteEditor();
                    renderMap();
                    persistToLocal();
                }
            });

            refs.routeEditor.addEventListener("change", (event) => {
                const target = event.target;
                if (!(target instanceof HTMLSelectElement)) {
                    return;
                }
                if (target.classList.contains("move-bus-select")) {
                    if (!state.manualMode) {
                        return;
                    }
                    const stopKey = target.dataset.stopKey;
                    const fromBus = Number(target.dataset.fromBus);
                    const toBus = Number(target.value);
                    if (Number.isFinite(fromBus) && Number.isFinite(toBus) && fromBus !== toBus) {
                        pushHistory();
                        moveStopToBus(stopKey, fromBus, toBus);
                        renderAll();
                    }
                }
            });

            refs.routeEditor.addEventListener("dragstart", (event) => {
                if (!state.manualMode) {
                    return;
                }
                const target = event.target;
                if (!(target instanceof HTMLElement) || !target.classList.contains("manual-stop-item")) {
                    return;
                }
                dragSource = {
                    stopKey: target.dataset.stopKey,
                    busNumber: Number(target.dataset.busNumber),
                };
                target.classList.add("dragging");
            });

            refs.routeEditor.addEventListener("dragend", (event) => {
                const target = event.target;
                if (target instanceof HTMLElement) {
                    target.classList.remove("dragging");
                }
            });

            refs.routeEditor.addEventListener("dragover", (event) => {
                if (!state.manualMode) {
                    return;
                }
                const target = event.target;
                if (!(target instanceof HTMLElement)) {
                    return;
                }
                if (target.closest(".manual-stop-item")) {
                    event.preventDefault();
                }
            });

            refs.routeEditor.addEventListener("drop", (event) => {
                if (!state.manualMode || !dragSource) {
                    return;
                }
                const target = event.target;
                if (!(target instanceof HTMLElement)) {
                    return;
                }
                const dropItem = target.closest(".manual-stop-item");
                if (!dropItem) {
                    return;
                }
                const targetBus = Number(dropItem.dataset.busNumber);
                const targetStopKey = dropItem.dataset.stopKey;
                if (!Number.isFinite(targetBus) || targetBus !== dragSource.busNumber) {
                    return;
                }
                pushHistory();
                reorderStopWithinBus(targetBus, dragSource.stopKey, targetStopKey);
                dragSource = null;
                renderAll();
            });
        }
    }

    function renderAll() {
        refreshStudentIndex();
        applyCapacityConstraints();
        recomputeAllBuses();
        renderControls();
        renderCapacityPreview();
        renderAdminMetrics();
        renderAssignments();
        renderRouteEditor();
        renderMap();
        persistToLocal();
    }

    function refreshStudentIndex() {
        studentIndex = new Map(state.students.map((student) => [student.id, student]));
    }

    function renderControls() {
        if (refs.modeToggleBtn) {
            refs.modeToggleBtn.dataset.manual = String(state.manualMode);
            refs.modeToggleBtn.textContent = state.manualMode ? "AI Mode" : "Manual Edit Mode";
        }
        if (refs.undoBtn) {
            refs.undoBtn.disabled = state.history.length === 0;
        }
        if (refs.redoBtn) {
            refs.redoBtn.disabled = state.future.length === 0;
        }

        if (refs.newStopBus) {
            refs.newStopBus.innerHTML = state.buses
                .map((bus) => `<option value="${bus.bus_number}">Bus ${bus.bus_number}</option>`)
                .join("");
        }

        if (refs.occupancySlider) {
            refs.occupancySlider.value = String(state.settings.occupancyPercent);
            refs.occupancySlider.disabled = !state.manualMode;
        }
        if (refs.occupancyValue) {
            refs.occupancyValue.textContent = `${state.settings.occupancyPercent}%`;
        }
        if (refs.overflowModeToggle) {
            refs.overflowModeToggle.checked = state.settings.overflowEnabled;
            refs.overflowModeToggle.disabled = !state.manualMode;
        }
        if (refs.overflowLimitInput) {
            refs.overflowLimitInput.value = String(state.settings.overflowLimitPerBus);
            refs.overflowLimitInput.disabled = !state.manualMode || !state.settings.overflowEnabled;
        }
        refreshOverflowHint();

        const editableControls = [
            refs.addStopBtn,
            refs.newStopName,
            refs.newStopLat,
            refs.newStopLon,
            refs.newStopBus,
        ];
        editableControls.forEach((node) => {
            if (!node) {
                return;
            }
            node.disabled = !state.manualMode;
        });
    }

    function ensureOverflowHintNode() {
        if (!refs.overflowLimitInput) {
            return null;
        }
        let hint = document.getElementById(overflowHintId);
        if (!hint) {
            hint = document.createElement("p");
            hint.id = overflowHintId;
            hint.className = "hint";
            hint.style.color = "#fcd34d";
            refs.overflowLimitInput.insertAdjacentElement("afterend", hint);
        }
        return hint;
    }

    function refreshOverflowHint() {
        if (!refs.overflowLimitInput || !refs.overflowModeToggle) {
            return;
        }
        const hint = ensureOverflowHintNode();
        if (!hint) {
            return;
        }
        const limit = Number(refs.overflowLimitInput.value || 0);
        if (limit > 0 && !refs.overflowModeToggle.checked) {
            hint.textContent = "Overflow limit is ignored until Overflow Mode is ON.";
        } else {
            hint.textContent = "";
        }
    }

    function renderAssignments() {
        if (!refs.assignmentsBody) {
            return;
        }
        const stopOptions = buildStopOptions();
        const students = state.students.slice(0, 400);
        refs.assignmentsBody.innerHTML = students.map((student) => {
            const stop = findStopByKey(student.stopKey);
            const busLabel = stop ? `Bus ${stop.bus_number}` : "Unassigned";
            const pickup = stop ? stop.pickup_time : "--:--";
            const current = stop ? `${stop.name} (${stop.stop_id})` : "Unassigned";
            const optionsHtml = [
                `<option value="">Unassigned</option>`,
                ...stopOptions.map((item) => `<option value="${item.key}" ${item.key === student.stopKey ? "selected" : ""}>${item.label}</option>`),
            ].join("");
            return `
                <tr>
                    <td>${escapeHtml(student.student_name)}</td>
                    <td>${escapeHtml(current)}</td>
                    <td>${escapeHtml(busLabel)}</td>
                    <td>${escapeHtml(pickup)}</td>
                    <td>${escapeHtml(student.source_file || "")}</td>
                    <td>
                        <select class="assignment-stop-select" data-student-id="${student.id}" data-current="${student.stopKey || ""}" ${state.manualMode ? "" : "disabled"}>
                            ${optionsHtml}
                        </select>
                    </td>
                </tr>
            `;
        }).join("");
    }

    function getCapacityConfig(settingsOverride = null) {
        const settings = settingsOverride || state.settings;
        const actual = Math.max(1, Number(state.busCapacity) || 1);
        const plannedSeats = Math.max(1, Math.floor(actual * (Number(settings.occupancyPercent) / 100)));
        const overflow = settings.overflowEnabled ? Math.max(0, Number(settings.overflowLimitPerBus) || 0) : 0;
        const usable = plannedSeats + overflow;
        const safetyLimit = Math.floor(actual * 0.25);
        return {
            actualCapacity: actual,
            plannedSeats,
            overflowAllowed: overflow,
            usableCapacity: usable,
            safetyLimit,
        };
    }

    function renderCapacityPreview() {
        const cfg = getCapacityConfig();
        if (refs.previewActualCapacity) refs.previewActualCapacity.textContent = String(cfg.actualCapacity);
        if (refs.previewPlannedOccupancy) refs.previewPlannedOccupancy.textContent = `${state.settings.occupancyPercent}%`;
        if (refs.previewPlannedSeats) refs.previewPlannedSeats.textContent = String(cfg.plannedSeats);
        if (refs.previewOverflowAllowed) refs.previewOverflowAllowed.textContent = `+${cfg.overflowAllowed}`;
        if (refs.previewMaxAllowed) refs.previewMaxAllowed.textContent = String(cfg.usableCapacity);

        if (refs.overflowSafetyWarning) {
            const overflowTooHigh = state.settings.overflowEnabled && cfg.overflowAllowed > cfg.safetyLimit;
            refs.overflowSafetyWarning.hidden = !overflowTooHigh;
            refs.overflowSafetyWarning.textContent = overflowTooHigh
                ? `Safety warning: overflow exceeds +25% of actual capacity (${cfg.safetyLimit}).`
                : "";
        }
    }

    function renderRouteEditor() {
        if (!refs.routeEditor) {
            return;
        }
        const controlsHtml = `
            <div class="map-focus-controls">
                <button class="btn btn-secondary-dark show-all-routes-btn" type="button">Show All Routes</button>
                <span class="hint">${state.activeBusId ? `Focused: Bus ${state.activeBusId}` : "Focused: All Routes"}</span>
            </div>
        `;
        const cardsHtml = state.buses.map((bus, busIndex) => {
            const health = computeBusHealth(bus);
            const stopItems = bus.stops.map((stop) => {
                const moveSelect = `
                    <select class="move-bus-select" data-stop-key="${stop.key}" data-from-bus="${bus.bus_number}" ${state.manualMode && !stop.locked ? "" : "disabled"}>
                        ${state.buses.map((b) => `<option value="${b.bus_number}" ${b.bus_number === bus.bus_number ? "selected" : ""}>Bus ${b.bus_number}</option>`).join("")}
                    </select>
                `;
                return `
                    <li class="manual-stop-item ${stop.locked ? "locked-stop" : ""}" draggable="${state.manualMode ? "true" : "false"}" data-stop-key="${stop.key}" data-bus-number="${bus.bus_number}">
                        <span class="drag-handle">::</span>
                        <div class="manual-stop-main">
                            <strong>Stop ${stop.stop_number} - ${escapeHtml(stop.name)} (${escapeHtml(stop.stop_id)})</strong>
                            <span class="stop-meta">Students: ${stop.students.length} | Pickup: ${stop.pickup_time} | Boarding: ${stop.boarding_time}</span>
                        </div>
                        <div class="manual-stop-actions">
                            <button class="lock-stop-btn btn btn-secondary-dark" type="button" data-stop-key="${stop.key}" ${state.manualMode ? "" : "disabled"}>${stop.locked ? "Unlock" : "Lock"}</button>
                            ${moveSelect}
                            <button class="remove-stop-btn btn btn-secondary-dark" type="button" data-stop-key="${stop.key}" ${state.manualMode && !stop.locked ? "" : "disabled"}>Remove</button>
                        </div>
                    </li>
                `;
            }).join("");

            return `
                <article class="bus-card route-card interactive-card motion-reveal reveal-up ${health.visualClass}">
                    <h2>Bus ${bus.bus_number}</h2>
                    <div class="route-health-grid">
                        <div class="route-health-pill">Health Score: ${health.healthScore}</div>
                        <div class="route-health-pill risk-badge ${health.riskClass}">Health: ${health.statusLabel}</div>
                        <div class="route-health-pill">Planned Occupancy: ${health.plannedOccupancyPercent}%</div>
                        <div class="route-health-pill">Actual Occupancy: ${health.actualOccupancyPercent}%</div>
                        <div class="route-health-pill">Overflow Count: ${health.overflowCount}</div>
                        <div class="route-health-pill">Efficiency: ${health.efficiencyPercent}%</div>
                        <div class="route-health-pill">Stop Density: ${health.stopDensity}</div>
                        <div class="route-health-pill">Overlap: ${health.overlapScore}</div>
                    </div>
                    <p><strong>Total Students:</strong> ${bus.total_students}</p>
                    <p><strong>Actual Capacity:</strong> ${Math.max(1, Number(bus.actual_capacity || state.busCapacity || 1))}</p>
                    <p><strong>Arrival Time:</strong> ${bus.arrival_time}</p>
                    <p><strong>Route Distance:</strong> ${bus.route_distance_km} km</p>
                    <p><strong>Route Duration:</strong> ${bus.route_duration_min} min</p>
                    <p><strong>Boarding Time:</strong> ${bus.boarding_duration_min} min</p>
                    <p><strong>Primary Reason:</strong> ${escapeHtml(health.primaryReason)}</p>
                    <div class="manual-actions">
                        <button class="btn btn-secondary-dark view-on-map-btn" type="button" data-bus-number="${bus.bus_number}">
                            ${state.activeBusId === bus.bus_number ? "Viewing On Map" : "View On Map"}
                        </button>
                    </div>
                    <details class="quality-details" ${health.warnings.length ? "" : "open"}>
                        <summary>View Quality Details</summary>
                        <div class="quality-warning-list">
                            ${health.warnings.length
                                ? health.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")
                                : "<p>No notable quality warnings.</p>"}
                        </div>
                    </details>
                    <div class="stops-list-wrap">
                        <h3>Stops (Draggable)</h3>
                        <ol class="stops-list manual-stop-list bus-color-${busIndex % palette.length}">
                            ${stopItems}
                        </ol>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Stop #</th>
                                <th>Stop</th>
                                <th>Students</th>
                                <th>Boarding Time</th>
                                <th>Pickup Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${bus.stops.map((stop) => `
                                <tr>
                                    <td>${stop.stop_number}</td>
                                    <td>${escapeHtml(stop.stop_id)}</td>
                                    <td>${stop.students.length}</td>
                                    <td>${stop.boarding_time}</td>
                                    <td>${stop.pickup_time}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </article>
            `;
        }).join("");

        refs.routeEditor.innerHTML = controlsHtml + cardsHtml;

        refs.routeEditor.querySelectorAll(".motion-reveal").forEach((node) => node.classList.remove("motion-reveal"));
        refs.routeEditor.querySelectorAll(".card-tilt").forEach((node) => node.classList.remove("card-tilt"));
        initInteractiveCards(false);
    }

    function renderAdminMetrics() {
        if (!refs.metrics.totalBuses) {
            return;
        }

        const cfg = getCapacityConfig();
        const capacityLimit = state.settings.overflowEnabled ? cfg.usableCapacity : cfg.plannedSeats;
        const overloaded = state.buses.filter((bus) => bus.total_students > capacityLimit).length;
        const unassigned = state.students.filter((student) => !student.stopKey).length;
        const locked = state.buses.reduce((sum, bus) => sum + bus.stops.filter((stop) => stop.locked).length, 0);
        const healthSummary = summarizeRouteHealth(state.buses);
        const totalOverflowPassengers = state.buses.reduce(
            (sum, bus) => sum + Math.max(0, bus.total_students - cfg.plannedSeats),
            0
        );
        const busesUsingOverflow = state.buses.filter((bus) => bus.total_students > cfg.plannedSeats).length;
        const maxNetworkCapacity = capacityLimit * state.buses.length;
        const currentLoad = state.buses.reduce((sum, bus) => sum + bus.total_students, 0);
        const overloadPercentage = maxNetworkCapacity > 0
            ? roundTo((totalOverflowPassengers / maxNetworkCapacity) * 100, 1)
            : 0;
        const unusedCapacity = Math.max(0, maxNetworkCapacity - currentLoad);

        refs.metrics.totalBuses.textContent = String(state.buses.length);
        refs.metrics.overloaded.textContent = String(overloaded);
        refs.metrics.unassigned.textContent = String(unassigned);
        refs.metrics.locked.textContent = String(locked);
        refs.metrics.overrides.textContent = String(state.overrideActions);
        if (refs.metrics.totalOverflow) refs.metrics.totalOverflow.textContent = String(totalOverflowPassengers);
        if (refs.metrics.busesUsingOverflow) refs.metrics.busesUsingOverflow.textContent = String(busesUsingOverflow);
        if (refs.metrics.overloadPercent) refs.metrics.overloadPercent.textContent = `${overloadPercentage}%`;
        if (refs.metrics.unusedCapacity) refs.metrics.unusedCapacity.textContent = String(unusedCapacity);
        if (refs.metrics.healthyRoutes) refs.metrics.healthyRoutes.textContent = String(healthSummary.healthy);
        if (refs.metrics.cautionRoutes) refs.metrics.cautionRoutes.textContent = String(healthSummary.caution);
        if (refs.metrics.severeRoutes) refs.metrics.severeRoutes.textContent = String(healthSummary.severe);
    }

    function renderMap() {
        const mapElement = document.getElementById("map");
        if (!mapElement) {
            return;
        }

        if (!map) {
            map = L.map("map");
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                attribution: "&copy; OpenStreetMap contributors",
            }).addTo(map);
            map.createPane("routeGlowPane");
            map.getPane("routeGlowPane").style.zIndex = "390";
            map.createPane("routePane");
            map.getPane("routePane").style.zIndex = "410";
            map.createPane("stopPane");
            map.getPane("stopPane").style.zIndex = "430";

            routeLayer = L.layerGroup().addTo(map);
            markerLayer = L.layerGroup().addTo(map);
            focusedRouteLayer = L.layerGroup().addTo(map);
            focusedStopLayer = L.layerGroup().addTo(map);
            map.on("click", (event) => {
                if (!state.manualMode) {
                    return;
                }
                const defaultBus = Number(refs.newStopBus?.value) || state.buses[0]?.bus_number;
                if (!Number.isFinite(defaultBus)) {
                    return;
                }
                pushHistory();
                const stopName = `Custom Stop ${state.stopCounter}`;
                addCustomStop(stopName, event.latlng.lat, event.latlng.lng, defaultBus);
                renderAll();
            });
        }

        routeLayer.clearLayers();
        markerLayer.clearLayers();
        if (focusedRouteLayer) focusedRouteLayer.clearLayers();
        if (focusedStopLayer) focusedStopLayer.clearLayers();
        const bounds = L.latLngBounds();
        const focusBounds = L.latLngBounds();
        const activeBusId = Number.isFinite(Number(state.activeBusId)) ? Number(state.activeBusId) : null;
        const collegeMarker = L.marker([college.lat, college.lon]).addTo(markerLayer);
        collegeMarker.bindPopup(`<strong>${escapeHtml(college.name)}</strong>`);
        bounds.extend([college.lat, college.lon]);

        state.buses.forEach((bus, index) => {
            const color = palette[index % palette.length];
            const isFocused = activeBusId !== null && Number(bus.bus_number) === activeBusId;
            const isMuted = activeBusId !== null && !isFocused;
            const fallbackRoutePoints = bus.stops.map((stop) => [stop.lat, stop.lon]);
            if (fallbackRoutePoints.length) {
                fallbackRoutePoints.push([college.lat, college.lon]);
            }
            const hasRouteGeometry = Array.isArray(bus.route_geometry) && bus.route_geometry.length >= 2;
            const normalizedGeometry = (!bus.geometry_dirty && hasRouteGeometry)
                ? normalizeRouteGeometry(bus.route_geometry)
                : [];
            const routePoints = normalizedGeometry.length >= 2
                ? normalizedGeometry
                : fallbackRoutePoints;

            if (routePoints.length >= 2) {
                const routeTargetLayer = isFocused ? focusedRouteLayer : routeLayer;
                const glowLine = L.polyline(routePoints, {
                    color,
                    weight: isFocused ? 11 : 9,
                    opacity: isMuted ? 0.06 : (isFocused ? 0.33 : 0.2),
                    smoothFactor: 0,
                    lineJoin: "round",
                    lineCap: "round",
                    noClip: true,
                    pane: isFocused ? "routePane" : "routeGlowPane",
                    interactive: false,
                }).addTo(routeTargetLayer);

                const polyline = L.polyline(routePoints, {
                    color,
                    weight: isFocused ? 7 : 5,
                    opacity: isMuted ? 0.24 : 0.95,
                    smoothFactor: 0,
                    lineJoin: "round",
                    lineCap: "round",
                    noClip: true,
                    pane: "routePane",
                }).addTo(routeTargetLayer);

                polyline.on("mouseover", () => {
                    polyline.setStyle({ weight: 7, opacity: 1 });
                    glowLine.setStyle({ opacity: 0.28 });
                });
                polyline.on("mouseout", () => {
                    polyline.setStyle({ weight: 5, opacity: 0.95 });
                    glowLine.setStyle({ opacity: 0.2 });
                });

                const path = polyline.getElement();
                if (path) path.classList.add("animated-route-line");

                routePoints.forEach((point) => {
                    bounds.extend(point);
                    if (isFocused) focusBounds.extend(point);
                });
            }

            bus.stops.forEach((stop) => {
                if (isMuted) {
                    return;
                }
                const assignedStudents = (stop.students || [])
                    .map((studentId) => studentIndex.get(studentId)?.student_name)
                    .filter(Boolean);
                const assignedStudentsLabel = assignedStudents.length
                    ? assignedStudents.map((name) => escapeHtml(String(name))).join(", ")
                    : "None";
                const isFirst = Number(stop.stop_number) === 1;
                const isLast = Number(stop.stop_number) === Number(bus.stops.length);
                const stopRoleClass = isFirst ? "stop-role-start" : (isLast ? "stop-role-final" : "stop-role-mid");
                const markerTargetLayer = isFocused ? focusedStopLayer : markerLayer;
                const marker = L.marker([stop.lat, stop.lon], {
                    draggable: state.manualMode && !stop.locked,
                    icon: L.divIcon({
                        className: "manual-stop-icon",
                        html: `
                            <span class="manual-stop-dot modern-stop-marker ${stopRoleClass}" style="--stop-color:${color}">
                                <span class="stop-seq">${Number(stop.stop_number || 0)}</span>
                            </span>
                        `,
                    }),
                    pane: "stopPane",
                }).addTo(markerTargetLayer);
                marker.bindTooltip(`S${Number(stop.stop_number || 0)}`, {
                    direction: "top",
                    offset: [0, -10],
                    permanent: true,
                    className: "route-stop-tooltip",
                });

                marker.on("dragend", (event) => {
                    if (!state.manualMode || stop.locked) {
                        return;
                    }
                    const newPos = event.target.getLatLng();
                    pushHistory();
                    stop.lat = Number(newPos.lat.toFixed(6));
                    stop.lon = Number(newPos.lng.toFixed(6));
                    bus.geometry_dirty = true;
                    renderAll();
                });

                marker.bindPopup(
                    `<strong>Stop ${stop.stop_number} - ${escapeHtml(stop.name)} (${escapeHtml(stop.stop_id)})</strong><br>` +
                    `Bus Number: ${bus.bus_number}<br>` +
                    `Pickup Time: ${stop.pickup_time}<br>` +
                    `Students Count: ${stop.students.length}<br>` +
                    `Boarding Duration: ${escapeHtml(stop.boarding_time || "0m 00s")}<br>` +
                    `Corridor: ${escapeHtml(stop.corridor || "-")}<br>` +
                    `Assigned Students: ${assignedStudentsLabel}`
                );

                const markerElement = marker.getElement();
                if (markerElement) {
                    markerElement.classList.add("pulse-stop-marker");
                    if (isFocused) markerElement.classList.add("focused-stop-marker");
                }
                bounds.extend([stop.lat, stop.lon]);
                if (isFocused) focusBounds.extend([stop.lat, stop.lon]);
            });
        });

        if (bounds.isValid()) {
            if (focusBounds.isValid()) {
                map.fitBounds(focusBounds.pad(0.2), { maxZoom: 14 });
                hasFittedBounds = true;
            } else if (!hasFittedBounds) {
                map.fitBounds(bounds.pad(0.18));
                hasFittedBounds = true;
            }
        } else {
            map.setView([college.lat, college.lon], 12);
        }
    }

    function normalizeRouteGeometry(points) {
        if (!Array.isArray(points)) {
            return [];
        }
        const normalized = [];
        const collegeLat = Number(college.lat) || 0;
        const collegeLon = Number(college.lon) || 0;
        let previous = null;
        for (const point of points) {
            if (!Array.isArray(point) || point.length < 2) continue;
            const a = [Number(point[0]), Number(point[1])];
            const b = [Number(point[1]), Number(point[0])];
            const candidates = [a, b].filter(([lat, lon]) => (
                Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
            ));
            if (!candidates.length) continue;
            const score = ([lat, lon]) => {
                const collegeDistance = haversineKm(lat, lon, collegeLat, collegeLon);
                const continuity = previous ? haversineKm(lat, lon, previous[0], previous[1]) * 1.25 : 0;
                return collegeDistance + continuity;
            };
            const best = candidates.reduce((acc, cur) => (score(cur) < score(acc) ? cur : acc));
            normalized.push(best);
            previous = best;
        }
        return normalized;
    }

    function addCustomStop(name, lat, lon, busNumber) {
        const bus = state.buses.find((item) => item.bus_number === Number(busNumber));
        if (!bus) {
            return;
        }
        const newStop = {
            key: `custom-${state.stopCounter++}`,
            stop_id: `C${state.stopCounter}`,
            name,
            lat,
            lon,
            students: [],
            stop_number: bus.stops.length + 1,
            pickup_time: "--:--",
            boarding_time: "0m 00s",
            locked: false,
            source: "manual",
        };
        bus.stops.push(newStop);
        bus.geometry_dirty = true;
        state.overrideActions += 1;
    }

    function removeStop(stopKey) {
        const position = findStopLocation(stopKey);
        if (!position) {
            return;
        }
        const { bus, stopIndex } = position;
        const stop = bus.stops[stopIndex];
        if (stop.locked) {
            return;
        }

        const affectedStudents = [...stop.students];
        affectedStudents.forEach((studentId) => {
            const student = studentIndex.get(studentId);
            if (student) {
                student.stopKey = null;
            }
        });
        bus.stops.splice(stopIndex, 1);
        bus.geometry_dirty = true;
        state.overrideActions += 1;
    }

    function toggleStopLock(stopKey) {
        const stop = findStopByKey(stopKey);
        if (!stop) {
            return;
        }
        stop.locked = !stop.locked;
        state.overrideActions += 1;
    }

    function moveStopToBus(stopKey, fromBusNumber, toBusNumber) {
        const fromBus = state.buses.find((bus) => bus.bus_number === Number(fromBusNumber));
        const toBus = state.buses.find((bus) => bus.bus_number === Number(toBusNumber));
        if (!fromBus || !toBus || fromBus === toBus) {
            return;
        }

        const index = fromBus.stops.findIndex((stop) => stop.key === stopKey);
        if (index < 0) {
            return;
        }

        const stop = fromBus.stops[index];
        if (stop.locked) {
            return;
        }
        fromBus.stops.splice(index, 1);
        stop.bus_number = toBus.bus_number;
        toBus.stops.push(stop);
        fromBus.geometry_dirty = true;
        toBus.geometry_dirty = true;

        stop.students.forEach((studentId) => {
            const student = studentIndex.get(studentId);
            if (student) {
                student.bus_number = toBus.bus_number;
            }
        });
        state.overrideActions += 1;
    }

    function reorderStopWithinBus(busNumber, fromStopKey, toStopKey) {
        const bus = state.buses.find((item) => item.bus_number === Number(busNumber));
        if (!bus) {
            return;
        }
        const fromIndex = bus.stops.findIndex((stop) => stop.key === fromStopKey);
        const toIndex = bus.stops.findIndex((stop) => stop.key === toStopKey);
        if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) {
            return;
        }

        const sourceStop = bus.stops[fromIndex];
        if (sourceStop.locked) {
            return;
        }

        const [moved] = bus.stops.splice(fromIndex, 1);
        bus.stops.splice(toIndex, 0, moved);
        bus.geometry_dirty = true;
        state.overrideActions += 1;
    }

    function reassignStudentToStop(studentId, stopKey) {
        const student = studentIndex.get(studentId);
        if (!student) {
            return;
        }

        if (student.stopKey) {
            const oldStop = findStopByKey(student.stopKey);
            if (oldStop) {
                oldStop.students = oldStop.students.filter((id) => id !== student.id);
            }
        }

        student.stopKey = stopKey || null;
        if (!stopKey) {
            student.bus_number = null;
            student.pickup_time = "--:--";
            state.overrideActions += 1;
            return;
        }

        const newStop = findStopByKey(stopKey);
        if (!newStop) {
            student.stopKey = null;
            student.bus_number = null;
            student.pickup_time = "--:--";
            return;
        }

        newStop.students.push(student.id);
        student.bus_number = newStop.bus_number;
        state.overrideActions += 1;
    }

    function applyCapacityConstraints() {
        const cfg = getCapacityConfig();
        const stopMap = new Map();
        state.buses.forEach((bus) => {
            bus.stops.forEach((stop) => {
                stop.students = [];
                stopMap.set(stop.key, stop);
            });
        });

        state.students.forEach((student) => {
            if (!student.stopKey) {
                return;
            }
            const stop = stopMap.get(student.stopKey);
            if (!stop) {
                student.stopKey = null;
                student.bus_number = null;
                student.pickup_time = "--:--";
                return;
            }
            stop.students.push(student.id);
            student.bus_number = stop.bus_number;
        });

        const busLoadMap = new Map(state.buses.map((bus) => [bus.bus_number, currentBusLoad(bus)]));
        const unassignedIds = new Set(state.students.filter((student) => !student.stopKey).map((student) => student.id));

        state.buses.forEach((bus) => {
            const usableLimit = state.settings.overflowEnabled ? cfg.usableCapacity : cfg.plannedSeats;
            let load = busLoadMap.get(bus.bus_number) || 0;
            if (load <= usableLimit) {
                return;
            }
            let toRemove = load - usableLimit;
            for (let s = bus.stops.length - 1; s >= 0 && toRemove > 0; s -= 1) {
                const stop = bus.stops[s];
                while (stop.students.length && toRemove > 0) {
                    const removed = stop.students.pop();
                    const student = studentIndex.get(removed);
                    if (student) {
                        student.stopKey = null;
                        student.bus_number = null;
                        student.pickup_time = "--:--";
                    }
                    unassignedIds.add(removed);
                    load -= 1;
                    toRemove -= 1;
                }
            }
            busLoadMap.set(bus.bus_number, load);
        });

        const unassignedQueue = [...unassignedIds];
        if (!unassignedQueue.length) {
            return;
        }

        const assignInPhase = (phaseLimit) => {
            for (let i = 0; i < unassignedQueue.length; i += 1) {
                const studentId = unassignedQueue[i];
                if (!studentId) {
                    continue;
                }
                const targetBus = pickBestBusForCapacity(busLoadMap, phaseLimit);
                if (!targetBus) {
                    continue;
                }
                const stop = pickStopForBus(targetBus);
                if (!stop) {
                    continue;
                }
                stop.students.push(studentId);
                busLoadMap.set(targetBus.bus_number, (busLoadMap.get(targetBus.bus_number) || 0) + 1);
                const student = studentIndex.get(studentId);
                if (student) {
                    student.stopKey = stop.key;
                    student.bus_number = targetBus.bus_number;
                }
                unassignedQueue[i] = "";
            }
        };

        assignInPhase(cfg.plannedSeats);
        if (state.settings.overflowEnabled) {
            assignInPhase(cfg.usableCapacity);
        }

        const remainingUnassigned = unassignedQueue.filter(Boolean);
        remainingUnassigned.forEach((studentId) => {
            const student = studentIndex.get(studentId);
            if (student) {
                student.stopKey = null;
                student.bus_number = null;
                student.pickup_time = "--:--";
            }
        });

        if (refs.overflowSuggestion) {
            if (remainingUnassigned.length > 0) {
                const busesCount = Math.max(1, state.buses.length);
                const required = Math.ceil(remainingUnassigned.length / busesCount);
                refs.overflowSuggestion.textContent = `Suggested overflow required: +${required} seats per bus to absorb remaining unassigned students.`;
            } else {
                refs.overflowSuggestion.textContent = "All students assigned within current planned + overflow limits.";
            }
        }
    }

    function pickBestBusForCapacity(busLoadMap, capacityLimit) {
        const candidates = state.buses
            .map((bus) => ({ bus, load: busLoadMap.get(bus.bus_number) || 0 }))
            .filter((item) => item.load < capacityLimit && item.bus.stops.length > 0)
            .sort((a, b) => a.load - b.load);
        return candidates.length ? candidates[0].bus : null;
    }

    function pickStopForBus(bus) {
        if (!bus.stops.length) {
            return null;
        }
        return [...bus.stops].sort((a, b) => a.students.length - b.students.length)[0];
    }

    function currentBusLoad(bus) {
        return bus.stops.reduce((sumLoad, stop) => sumLoad + stop.students.length, 0);
    }

    function recomputeAllBuses() {
        state.buses.forEach((bus) => {
            recomputeBusRoute(bus);
        });

        state.students.forEach((student) => {
            const stop = findStopByKey(student.stopKey);
            if (!stop) {
                student.bus_number = null;
                student.pickup_time = "--:--";
                return;
            }
            student.bus_number = stop.bus_number;
            student.pickup_time = stop.pickup_time;
        });
    }

    function recomputeBusRoute(bus) {
        let totalStudents = 0;
        let totalDistanceKm = 0;

        bus.stops.forEach((stop, index) => {
            stop.stop_number = index + 1;
            stop.students = dedupe(stop.students);
            totalStudents += stop.students.length;
        });

        const legMinutes = [];
        for (let i = 0; i < bus.stops.length; i += 1) {
            const current = bus.stops[i];
            const next = bus.stops[i + 1];
            if (next) {
                const distance = haversineKm(current.lat, current.lon, next.lat, next.lon);
                totalDistanceKm += distance;
                legMinutes.push((distance / 22) * 60);
            } else {
                const finalDistance = haversineKm(current.lat, current.lon, college.lat, college.lon);
                totalDistanceKm += finalDistance;
                legMinutes.push((finalDistance / 22) * 60);
            }
        }

        const boardingMinutesByStop = bus.stops.map((stop) => {
            const minutes = (stop.students.length * 4) / 60;
            stop.boarding_time = formatBoarding(minutes);
            return minutes;
        });

        const arrivalMinutes = parseTimeToMinutes(bus.arrival_time || "08:30");
        for (let i = 0; i < bus.stops.length; i += 1) {
            const remainingDrive = sum(legMinutes.slice(i));
            const remainingBoarding = sum(boardingMinutesByStop.slice(i));
            const pickupMinutes = arrivalMinutes - remainingDrive - remainingBoarding;
            bus.stops[i].pickup_time = minutesToHHMM(pickupMinutes);
        }

        bus.total_students = totalStudents;
        bus.route_distance_km = roundTo(totalDistanceKm, 2);
        const routeDuration = sum(legMinutes) + sum(boardingMinutesByStop);
        bus.route_duration_min = roundTo(routeDuration, 1);
        bus.boarding_duration_min = roundTo(sum(boardingMinutesByStop), 1);
    }

    function averageRouteOverlap(bus, buses) {
        const peers = (buses || []).filter((item) => item.bus_number !== bus.bus_number);
        if (!peers.length || bus.stops.length < 2) {
            return 0;
        }
        const segmentsFor = (stops) => {
            const segments = [];
            for (let i = 0; i < stops.length - 1; i += 1) {
                segments.push([
                    [(Number(stops[i].lat) + Number(stops[i + 1].lat)) / 2, (Number(stops[i].lon) + Number(stops[i + 1].lon)) / 2],
                    i,
                ]);
            }
            return segments;
        };
        const sourceSegments = segmentsFor(bus.stops);
        if (!sourceSegments.length) {
            return 0;
        }
        let overlapHits = 0;
        peers.forEach((peer) => {
            const peerSegments = segmentsFor(peer.stops);
            sourceSegments.forEach(([mid]) => {
                const hasNearby = peerSegments.some(([peerMid]) => haversineKm(mid[0], mid[1], peerMid[0], peerMid[1]) <= 0.75);
                if (hasNearby) {
                    overlapHits += 1;
                }
            });
        });
        return roundTo(overlapHits / Math.max(1, sourceSegments.length * peers.length), 3);
    }

    function computeRouteDiagnostics(bus, compareBuses = state.buses, settingsOverride = null) {
        const cfg = getCapacityConfig(settingsOverride);
        const capacity = Math.max(1, Number(bus.actual_capacity || cfg.actualCapacity));
        const plannedCapacity = Math.max(
            1,
            Math.floor(capacity * (Number((settingsOverride || state.settings).occupancyPercent) / 100))
                + (Boolean((settingsOverride || state.settings).overflowEnabled) ? Math.max(0, Number((settingsOverride || state.settings).overflowLimitPerBus) || 0) : 0)
        );
        const actualOccupancyPercent = roundTo((bus.total_students / capacity) * 100, 1);
        const plannedOccupancyPercent = roundTo((bus.total_students / plannedCapacity) * 100, 1);
        const overflowCount = Math.max(0, bus.total_students - plannedCapacity);
        const baselineDistance = state.baselineDistanceByBus.get(bus.bus_number) || bus.route_distance_km || 1;
        const efficiencyPercent = roundTo((baselineDistance / Math.max(bus.route_distance_km, 0.1)) * 100, 1);
        const density = bus.stops.length ? roundTo(bus.total_students / bus.stops.length, 1) : 0;
        const durationLimit = normalizeConstraintValue(window.SMARTROUTE_RESULTS?.configuredMaxRideDuration, null);
        const overlapScore = averageRouteOverlap(bus, compareBuses);
        const coords = bus.stops.map((stop) => [Number(stop.lat), Number(stop.lon)]);
        const diameter = coords.length
            ? Math.max(...coords.flatMap((a) => coords.map((b) => haversineKm(a[0], a[1], b[0], b[1]))))
            : 0.1;
        const compactness = roundTo(Number(bus.route_distance_km || 0) / Math.max(0.1, diameter || 0.1), 2);
        const spacingValues = [];
        for (let i = 0; i < bus.stops.length - 1; i += 1) {
            spacingValues.push(haversineKm(bus.stops[i].lat, bus.stops[i].lon, bus.stops[i + 1].lat, bus.stops[i + 1].lon));
        }
        const averageSpacing = spacingValues.length ? roundTo(sum(spacingValues) / spacingValues.length, 2) : 0;
        const farthestToCollege = Math.max(
            ...bus.stops.map((stop) => haversineKm(stop.lat, stop.lon, college.lat, college.lon)),
            0.1
        );
        const detourIndex = roundTo(Number(bus.route_distance_km || 0) / Math.max(0.1, farthestToCollege), 2);
        const warnings = [];
        let score = 100;

        const penalize = (points, message) => {
            score -= points;
            warnings.push(message);
        };

        if (durationLimit !== null) {
            const durationRatio = Number(bus.route_duration_min || 0) / Math.max(1, durationLimit);
            if (durationRatio >= 1.35) penalize(34, "Ride duration is far above the configured limit.");
            else if (durationRatio >= 1.15) penalize(18, "Ride duration is running longer than preferred.");
            else if (durationRatio >= 1.0) penalize(8, "Ride duration is approaching the configured limit.");
        }

        if (compactness >= 4.8) penalize(26, "Route compactness is very low for this service area.");
        else if (compactness >= 3.7) penalize(14, "Route compactness is below target and may indicate fragmentation.");
        else if (compactness >= 2.8) penalize(6, "Route compactness is slightly weaker than ideal.");

        if (overlapScore >= 0.75) penalize(24, "Severe route overlap detected with nearby buses.");
        else if (overlapScore >= 0.45) penalize(12, "Moderate route overlap detected.");
        else if (overlapScore >= 0.25) penalize(5, "Minor route overlap present.");

        if (averageSpacing >= 7.0) penalize(18, "Stop spacing is excessive across the route.");
        else if (averageSpacing >= 5.0) penalize(9, "Stop spacing is slightly high.");
        else if (averageSpacing >= 3.8) penalize(4, "Stop spacing is trending sparse.");

        if (detourIndex >= 3.6) penalize(16, "Route detour is high relative to direct campus approach.");
        else if (detourIndex >= 2.8) penalize(8, "Route detour is moderately elevated.");
        else if (detourIndex >= 2.2) penalize(3, "Route detour is slightly above ideal.");

        if (actualOccupancyPercent >= 118) penalize(16, "Occupancy is severely above standard operating target.");
        else if (actualOccupancyPercent >= 102) penalize(8, "Occupancy is moderately above target.");
        else if (bus.stops.length > 0 && actualOccupancyPercent <= 45 && Number(bus.route_distance_km || 0) >= 12) {
            penalize(6, "Route coverage is long for a relatively light load.");
        }

        if (bus.stops.length <= 2 && Number(bus.route_distance_km || 0) >= 18) penalize(15, "Too few stops are spread over a long route.");
        else if (bus.stops.length <= 3 && Number(bus.route_distance_km || 0) >= 12) penalize(8, "Stop distribution is sparse for the distance covered.");

        score = Math.max(0, roundTo(score, 1));
        let status = "green";
        let statusLabel = "Healthy";
        let riskClass = "risk-green";
        let visualClass = "bus-safe";
        if (score < 50) {
            status = "red";
            statusLabel = "Severe";
            riskClass = "risk-red";
            visualClass = "bus-overload";
        } else if (score < 80) {
            status = "yellow";
            statusLabel = "Caution";
            riskClass = "risk-yellow";
            visualClass = "bus-near-limit";
        }

        return {
            plannedOccupancyPercent,
            actualOccupancyPercent,
            overflowCount,
            efficiencyPercent,
            healthScore: score,
            healthState: status,
            statusLabel,
            riskClass,
            visualClass,
            stopDensity: `${density} students/stop`,
            overlapScore,
            compactness,
            averageSpacing,
            detourIndex,
            warnings,
            primaryReason: warnings[0] || "Route is operating within acceptable thresholds.",
        };
    }

    function computeBusHealth(bus) {
        return computeRouteDiagnostics(bus, state.buses, null);
    }

    function summarizeRouteHealth(buses, settingsOverride = null) {
        return (buses || []).reduce((summary, bus) => {
            const health = computeRouteDiagnostics(bus, buses || [], settingsOverride);
            if (health.healthState === "green") summary.healthy += 1;
            else if (health.healthState === "yellow") summary.caution += 1;
            else summary.severe += 1;
            return summary;
        }, { healthy: 0, caution: 0, severe: 0 });
    }

    function buildStopOptions() {
        const items = [];
        state.buses.forEach((bus) => {
            bus.stops.forEach((stop) => {
                items.push({
                    key: stop.key,
                    label: `Bus ${bus.bus_number} - ${stop.name} (${stop.stop_id})`,
                });
            });
        });
        return items;
    }

    function findStopByKey(stopKey) {
        if (!stopKey) {
            return null;
        }
        for (const bus of state.buses) {
            const found = bus.stops.find((stop) => stop.key === stopKey);
            if (found) {
                return found;
            }
        }
        return null;
    }

    function findStopLocation(stopKey) {
        for (const bus of state.buses) {
            const stopIndex = bus.stops.findIndex((stop) => stop.key === stopKey);
            if (stopIndex >= 0) {
                return { bus, stopIndex };
            }
        }
        return null;
    }

    function pushHistory() {
        state.history.push(snapshotState(state));
        if (state.history.length > 50) {
            state.history.shift();
        }
        state.future = [];
    }

    function undo() {
        if (!state.history.length) {
            return;
        }
        state.future.push(snapshotState(state));
        const previous = state.history.pop();
        restoreSnapshot(state, previous);
        renderAll();
    }

    function redo() {
        if (!state.future.length) {
            return;
        }
        state.history.push(snapshotState(state));
        const next = state.future.pop();
        restoreSnapshot(state, next);
        renderAll();
    }

    function snapshotState(runtimeState) {
        return JSON.stringify({
            buses: runtimeState.buses,
            students: runtimeState.students,
            activeBusId: runtimeState.activeBusId,
            manualMode: runtimeState.manualMode,
            overrideActions: runtimeState.overrideActions,
            stopCounter: runtimeState.stopCounter,
            settings: runtimeState.settings,
        });
    }

    function restoreSnapshot(runtimeState, snapshot) {
        const parsed = JSON.parse(snapshot);
        runtimeState.buses = parsed.buses || [];
        runtimeState.students = parsed.students || [];
        runtimeState.activeBusId = Number.isFinite(Number(parsed.activeBusId)) ? Number(parsed.activeBusId) : null;
        runtimeState.manualMode = Boolean(parsed.manualMode);
        runtimeState.overrideActions = Number(parsed.overrideActions) || 0;
        runtimeState.stopCounter = Number(parsed.stopCounter) || runtimeState.stopCounter;
        if (parsed.settings) {
            runtimeState.settings = {
                ...runtimeState.settings,
                occupancyPercent: Math.max(50, Math.min(120, Number(parsed.settings.occupancyPercent) || runtimeState.settings.occupancyPercent)),
                overflowEnabled: Boolean(parsed.settings.overflowEnabled),
                overflowLimitPerBus: Math.max(0, Math.round(Number(parsed.settings.overflowLimitPerBus) || 0)),
            };
        }
    }

    function savePlanFile() {
        const payload = {
            version: 1,
            savedAt: new Date().toISOString(),
            college,
            busCapacity: state.busCapacity,
            state: JSON.parse(snapshotState(state)),
        };
        downloadBlob(
            JSON.stringify(payload, null, 2),
            "smartroute_route_plan.json",
            "application/json"
        );
    }

    function loadPlanFromFile(event) {
        const file = event.target.files?.[0];
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            try {
                const parsed = JSON.parse(String(reader.result || "{}"));
                if (!parsed.state || !Array.isArray(parsed.state.buses) || !Array.isArray(parsed.state.students)) {
                    return;
                }
                pushHistory();
                restoreSnapshot(state, JSON.stringify(parsed.state));
                state.overrideActions += 1;
                renderAll();
            } catch {
                // Ignore malformed plans.
            }
        };
        reader.readAsText(file);
        event.target.value = "";
    }

    function exportAssignmentsJson() {
        const cfg = getCapacityConfig();
        const payload = state.students.map((student) => {
            const stop = findStopByKey(student.stopKey);
            const bus = stop ? state.buses.find((item) => item.bus_number === stop.bus_number) : null;
            const overflowUsed = bus ? Math.max(0, bus.total_students - cfg.plannedSeats) : 0;
            const actualCapacity = bus ? Math.max(1, Number(bus.actual_capacity || state.busCapacity || 1)) : Math.max(1, Number(state.busCapacity || 1));
            const overloadStatus = bus && bus.total_students > (state.settings.overflowEnabled ? cfg.usableCapacity : cfg.plannedSeats)
                ? "OVERLOAD"
                : overflowUsed > 0
                    ? "OVERFLOW_USED"
                    : "SAFE";
            return {
                student_name: student.student_name,
                stop_name: stop ? stop.name : "",
                stop_id: stop ? stop.stop_id : "",
                bus_number: stop ? stop.bus_number : "",
                pickup_time: stop ? stop.pickup_time : "",
                source_file: student.source_file || "",
                actual_capacity: actualCapacity,
                planned_capacity: cfg.plannedSeats,
                overflow_used: overflowUsed,
                overload_status: overloadStatus,
            };
        });
        downloadBlob(
            JSON.stringify(payload, null, 2),
            "smartroute_assignments.json",
            "application/json"
        );
    }

    function exportAssignmentsCsv() {
        const cfg = getCapacityConfig();
        const rows = ["student_name,stop_name,stop_id,bus_number,pickup_time,source_file,actual_capacity,planned_capacity,overflow_used,overload_status"];
        state.students.forEach((student) => {
            const stop = findStopByKey(student.stopKey);
            const bus = stop ? state.buses.find((item) => item.bus_number === stop.bus_number) : null;
            const overflowUsed = bus ? Math.max(0, bus.total_students - cfg.plannedSeats) : 0;
            const actualCapacity = bus ? Math.max(1, Number(bus.actual_capacity || state.busCapacity || 1)) : Math.max(1, Number(state.busCapacity || 1));
            const overloadStatus = bus && bus.total_students > (state.settings.overflowEnabled ? cfg.usableCapacity : cfg.plannedSeats)
                ? "OVERLOAD"
                : overflowUsed > 0
                    ? "OVERFLOW_USED"
                    : "SAFE";
            const values = [
                student.student_name,
                stop ? stop.name : "",
                stop ? stop.stop_id : "",
                stop ? String(stop.bus_number) : "",
                stop ? stop.pickup_time : "",
                student.source_file || "",
                String(actualCapacity),
                String(cfg.plannedSeats),
                String(overflowUsed),
                overloadStatus,
            ].map(csvEscape);
            rows.push(values.join(","));
        });
        downloadBlob(rows.join("\n"), "smartroute_assignments.csv", "text/csv");
    }

    function persistToLocal() {
        const signature = buildStateSignature(state);
        const payload = {
            version: 1,
            collegeName: college.name,
            signature,
            state: JSON.parse(snapshotState(state)),
        };
        localStorage.setItem(storageKey, JSON.stringify(payload));
    }

    function tryRestoreFromLocal() {
        const saved = localStorage.getItem(storageKey);
        if (!saved) {
            return;
        }
        try {
            const parsed = JSON.parse(saved);
            if (
                parsed?.state?.buses
                && parsed?.state?.students
                && parsed?.signature
                && parsed.signature === buildStateSignature(state)
            ) {
                restoreSnapshot(state, JSON.stringify(parsed.state));
            }
        } catch {
            // Ignore stale state.
        }
    }

    function buildStateSignature(runtimeState) {
        const busSignature = runtimeState.buses
            .slice()
            .sort((a, b) => Number(a.bus_number) - Number(b.bus_number))
            .map((bus) => {
                const stopSignature = bus.stops
                    .map((stop) => `${stop.stop_id}@${Number(stop.lat).toFixed(5)},${Number(stop.lon).toFixed(5)}`)
                    .join(">");
                return `${Number(bus.bus_number)}:${stopSignature}`;
            })
            .join("|");
        return `${runtimeState.students.length}|${runtimeState.buses.length}|${busSignature}`;
    }
}

function createInitialEditorState(resultsData, busCapacity, college) {
    const assignments = Array.isArray(resultsData.assignments) ? resultsData.assignments : [];
    const students = assignments.map((item, index) => ({
        id: `student-${index}`,
        student_name: String(item.student_name),
        bus_number: Number(item.bus_number),
        stop_name: String(item.stop_name),
        pickup_time: String(item.pickup_time || "--:--"),
        source_file: String(item.source_file || ""),
        stopKey: null,
    }));

    const buses = (resultsData.buses || []).map((bus) => {
        const busNumber = Number(bus.bus_number);
        const stops = (bus.ordered_stops || []).map((stop, index) => ({
            key: `bus-${busNumber}-stop-${index}-${stop.stop_id}`,
            stop_id: String(stop.stop_id),
            name: String(stop.name),
            lat: Number(stop.lat),
            lon: Number(stop.lon),
            students: [],
            stop_number: Number(stop.stop_number || index + 1),
            pickup_time: String(stop.pickup_time || "--:--"),
            boarding_time: String(stop.boarding_time || "0m 00s"),
            corridor: String(stop.corridor || ""),
            locked: false,
            bus_number: busNumber,
            source: "ai",
        }));

        return {
            bus_number: busNumber,
            arrival_time: String(bus.arrival_time || "08:30"),
            route_distance_km: Number(bus.route_distance_km || 0),
            route_duration_min: Number(bus.route_duration_min || 0),
            boarding_duration_min: Number(bus.boarding_duration_min || 0),
            total_students: Number(bus.total_students || 0),
            actual_capacity: Math.max(1, Number(bus.actual_capacity || resultsData.configuredBusCapacity || 1)),
            route_geometry: Array.isArray(bus.map_route_geometry)
                ? bus.map_route_geometry.map((point) => [Number(point[0]), Number(point[1])])
                : Array.isArray(bus.route_geometry)
                    ? bus.route_geometry.map((point) => [Number(point[0]), Number(point[1])])
                : [],
            geometry_dirty: false,
            stops,
        };
    });

    const stopLookup = new Map();
    buses.forEach((bus) => {
        bus.stops.forEach((stop) => {
            stopLookup.set(`${bus.bus_number}::${stop.name}`, stop.key);
        });
    });

    students.forEach((student) => {
        const key = stopLookup.get(`${student.bus_number}::${student.stop_name}`);
        if (key) {
            student.stopKey = key;
            const stop = findStopAcrossBuses(buses, key);
            if (stop) {
                stop.students.push(student.id);
            }
        } else {
            student.stopKey = null;
            student.bus_number = null;
            student.pickup_time = "--:--";
        }
    });

    const baselineDistanceByBus = new Map();
    buses.forEach((bus) => baselineDistanceByBus.set(bus.bus_number, Number(bus.route_distance_km || 0)));

    return {
        buses,
        students,
        busCapacity,
        college,
        settings: {
            occupancyPercent: 90,
            overflowEnabled: false,
            overflowLimitPerBus: 0,
        },
        activeBusId: null,
        manualMode: false,
        history: [],
        future: [],
        overrideActions: 0,
        stopCounter: 1 + buses.reduce((max, bus) => Math.max(max, bus.stops.length), 0),
        baselineDistanceByBus,
    };
}

function findStopAcrossBuses(buses, stopKey) {
    for (const bus of buses) {
        const stop = bus.stops.find((item) => item.key === stopKey);
        if (stop) {
            return stop;
        }
    }
    return null;
}

function csvEscape(value) {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes("\"") || text.includes("\n")) {
        return `"${text.replace(/"/g, "\"\"")}"`;
    }
    return text;
}

function downloadBlob(content, fileName, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
}

function dedupe(items) {
    return [...new Set(items)];
}

function sum(values) {
    return values.reduce((total, value) => total + Number(value || 0), 0);
}

function roundTo(value, digits) {
    const power = 10 ** digits;
    return Math.round(Number(value || 0) * power) / power;
}

function parseTimeToMinutes(value) {
    const [hours, minutes] = String(value || "08:30").split(":").map((part) => Number(part));
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
        return 8 * 60 + 30;
    }
    return (hours * 60) + minutes;
}

function minutesToHHMM(minutes) {
    const normalized = ((Math.round(minutes) % (24 * 60)) + (24 * 60)) % (24 * 60);
    const hrs = Math.floor(normalized / 60);
    const mins = normalized % 60;
    return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

function formatBoarding(minutes) {
    const seconds = Math.max(0, Math.round(minutes * 60));
    const mins = Math.floor(seconds / 60);
    const rem = seconds % 60;
    return `${mins}m ${String(rem).padStart(2, "0")}s`;
}

function haversineKm(lat1, lon1, lat2, lon2) {
    const r = 6371;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = (Math.sin(dLat / 2) ** 2)
        + (Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * (Math.sin(dLon / 2) ** 2));
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return r * c;
}

function toRad(value) {
    return value * (Math.PI / 180);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
