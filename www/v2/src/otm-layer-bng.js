////////////////////////////////////////////////////////
//
// OTM Web Frontend - otm-layer-bng.js
//
// British National Grid (BNG) overlay layer
// Supports grid references to 100m precision, e.g. NY 123 456
//
////////////////////////////////////////////////////////

// --- OSGB36 / BNG coordinate conversion constants ---

// Airy 1830 ellipsoid
const _A  = 6377563.396;
const _B  = 6356256.909;
const _E2 = 1 - (_B * _B) / (_A * _A);

// WGS84 ellipsoid
const _AW  = 6378137.0;
const _BW  = 6356752.3142;
const _E2W = 1 - (_BW * _BW) / (_AW * _AW);

// National Grid Transverse Mercator parameters
const _F0   = 0.9996012717;
const _LAT0 = 49.0 * Math.PI / 180;  // true origin: 49°N
const _LON0 = -2.0 * Math.PI / 180;  // true origin: 2°W
const _N0   = -100000;                // false northing (m)
const _E0   =  400000;                // false easting (m)

// Helmert 7-parameter transformation: OSGB36 → WGS84
const _TX =  446.448,  _TY = -125.157, _TZ = 542.060;  // metres
const _RX =  0.1502 / 206264.806;  // arcseconds → radians
const _RY =  0.2470 / 206264.806;
const _RZ =  0.8421 / 206264.806;
const _S  =  20.4894e-6;            // parts per million (scale)

// BNG letter table: A–Z excluding I (25 letters for the 5×5 sub-grid)
const _LETTERS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ';

// BNG valid extent (metres), generous to cover all of UK
const _E_MIN =      0;
const _E_MAX = 700000;
const _N_MIN =      0;
const _N_MAX = 1300000;

// --- Coordinate conversion helpers ---

// Helmert meridional arc from LAT0 to phi (OSGB36 parameters)
function _arc(phi) {
    const n = (_A - _B) / (_A + _B);
    const n2 = n * n, n3 = n2 * n;
    const dp = phi + _LAT0, dm = phi - _LAT0;
    return _B * _F0 * (
        (1 + n + 1.25*n2 + 1.25*n3) * dm
        - (3*n + 3*n2 + 2.625*n3) * Math.sin(dm) * Math.cos(dp)
        + (1.875*n2 + 1.875*n3)    * Math.sin(2*dm) * Math.cos(2*dp)
        - (35/24)*n3               * Math.sin(3*dm) * Math.cos(3*dp)
    );
}

// BNG easting/northing (metres) → WGS84 [lat, lon] in degrees
function _bng_to_wgs84(E, N) {
    // Iterative footpoint latitude
    let phi = _LAT0, M = 0, iter = 0;
    do {
        phi = (N - _N0 - M) / (_A * _F0) + phi;
        M   = _arc(phi);
    } while (Math.abs(N - _N0 - M) > 0.001 && ++iter < 100);

    const sp = Math.sin(phi), cp = Math.cos(phi), tp = sp / cp;
    const t2 = tp*tp, t4 = t2*t2;
    const nu  = _A * _F0 / Math.sqrt(1 - _E2 * sp*sp);
    const rho = _A * _F0 * (1 - _E2) / Math.pow(1 - _E2 * sp*sp, 1.5);
    const h2  = nu/rho - 1;
    const dE  = E - _E0;

    // Inverse TM series for lat and lon (OSGB36)
    const phi_o = phi
        - tp*dE*dE / (2*rho*nu)
        + tp*dE*dE*dE*dE / (24*rho*nu*nu*nu) * (5 + 3*t2 + h2 - 9*t2*h2)
        - tp*dE*dE*dE*dE*dE*dE / (720*rho*Math.pow(nu,5)) * (61 + 90*t2 + 45*t4);
    const lam_o = _LON0
        + dE / (cp*nu)
        - dE*dE*dE / (6*cp*nu*nu*nu) * (nu/rho + 2*t2)
        + dE*dE*dE*dE*dE / (120*cp*Math.pow(nu,5)) * (5 + 28*t2 + 24*t4)
        - dE*dE*dE*dE*dE*dE*dE / (5040*cp*Math.pow(nu,7)) * (61 + 662*t2 + 1320*t4 + 720*t2*t4);

    // OSGB36 → Cartesian (Airy 1830)
    const sp2 = Math.sin(phi_o), cp2 = Math.cos(phi_o);
    const nu2  = _A / Math.sqrt(1 - _E2 * sp2*sp2);
    const x1 = nu2 * cp2 * Math.cos(lam_o);
    const y1 = nu2 * cp2 * Math.sin(lam_o);
    const z1 = nu2 * (1 - _E2) * sp2;

    // Helmert: OSGB36 → WGS84
    const x2 = _TX + (1+_S)*x1 - _RZ*y1 + _RY*z1;
    const y2 = _TY + _RZ*x1 + (1+_S)*y1 - _RX*z1;
    const z2 = _TZ - _RY*x1 + _RX*y1 + (1+_S)*z1;

    // WGS84 Cartesian → lat/lon
    const lonW = Math.atan2(y2, x2);
    const p    = Math.sqrt(x2*x2 + y2*y2);
    let latW   = Math.atan2(z2, p * (1 - _E2W));
    for (let i = 0; i < 10; i++) {
        const nW = _AW / Math.sqrt(1 - _E2W * Math.sin(latW)*Math.sin(latW));
        latW = Math.atan2(z2 + _E2W * nW * Math.sin(latW), p);
    }
    return [latW * 180/Math.PI, lonW * 180/Math.PI];
}

// WGS84 [lat, lon] in degrees → BNG [easting, northing] in metres
function _wgs84_to_bng(lat, lon) {
    const lr = lat * Math.PI/180, lo = lon * Math.PI/180;
    const sp = Math.sin(lr), cp = Math.cos(lr);

    // WGS84 → Cartesian
    const nW = _AW / Math.sqrt(1 - _E2W * sp*sp);
    const x1 = nW * cp * Math.cos(lo);
    const y1 = nW * cp * Math.sin(lo);
    const z1 = nW * (1 - _E2W) * sp;

    // Helmert: WGS84 → OSGB36
    const x2 = -_TX + (1-_S)*x1 + _RZ*y1 - _RY*z1;
    const y2 = -_TY - _RZ*x1 + (1-_S)*y1 + _RX*z1;
    const z2 = -_TZ + _RY*x1 - _RX*y1 + (1-_S)*z1;

    // OSGB36 Cartesian → lat/lon
    const loO = Math.atan2(y2, x2);
    const p   = Math.sqrt(x2*x2 + y2*y2);
    let laO   = Math.atan2(z2, p * (1 - _E2));
    for (let i = 0; i < 10; i++) {
        const nA = _A / Math.sqrt(1 - _E2 * Math.sin(laO)*Math.sin(laO));
        laO = Math.atan2(z2 + _E2 * nA * Math.sin(laO), p);
    }

    // OSGB36 lat/lon → BNG easting/northing
    const sp2 = Math.sin(laO), cp2 = Math.cos(laO), tp = sp2/cp2;
    const t2 = tp*tp, t4 = t2*t2;
    const nu  = _A * _F0 / Math.sqrt(1 - _E2 * sp2*sp2);
    const rho = _A * _F0 * (1 - _E2) / Math.pow(1 - _E2 * sp2*sp2, 1.5);
    const h2  = nu/rho - 1;
    const M   = _arc(laO);
    const dL  = loO - _LON0;

    const N_bng = _N0 + M
        + (nu/2)   * sp2 * cp2 * dL*dL
        + (nu/24)  * sp2 * cp2*cp2*cp2 * (5 - t2 + 9*h2) * dL*dL*dL*dL
        + (nu/720) * sp2 * Math.pow(cp2,5) * (61 - 58*t2 + t4) * dL*dL*dL*dL*dL*dL;
    const E_bng = _E0
        + nu * cp2 * dL
        + (nu/6)   * cp2*cp2*cp2 * (nu/rho - t2) * dL*dL*dL
        + (nu/120) * Math.pow(cp2,5) * (5 - 18*t2 + t4 + 14*h2 - 58*t2*h2) * dL*dL*dL*dL*dL;

    return [E_bng, N_bng];
}

// --- BNG grid reference helpers ---

// Two-letter BNG square code for a given easting/northing
function _letters(E, N) {
    const c5 = Math.floor(E / 500000);
    const r5 = Math.floor(N / 500000);
    const l1 = _LETTERS[(3 - r5) * 5 + (c5 + 2)];
    const c1 = Math.floor((E % 500000) / 100000);
    const r1 = 4 - Math.floor((N % 500000) / 100000);
    const l2 = _LETTERS[r1 * 5 + c1];
    return (l1 || '?') + (l2 || '?');
}

// Format a grid reference label for the square SW corner at (E, N) with given step
function _ref(E, N, step) {
    const sE = Math.floor(E / step) * step;
    const sN = Math.floor(N / step) * step;
    const lt = _letters(sE, sN);
    if (step >= 100000) return lt;
    const eIn = sE % 100000;
    const nIn = sN % 100000;
    if (step >= 10000) {
        return lt + ' ' + Math.floor(eIn/10000) + ' ' + Math.floor(nIn/10000);
    }
    if (step >= 1000) {
        return lt + ' ' + String(Math.floor(eIn/1000)).padStart(2,'0')
                 + ' ' + String(Math.floor(nIn/1000)).padStart(2,'0');
    }
    return lt + ' ' + String(Math.floor(eIn/100)).padStart(3,'0')
              + ' ' + String(Math.floor(nIn/100)).padStart(3,'0');
}

// --- Leaflet layer ---

function otm_init_bng_factory() {

    L.BngGrid = L.Layer.extend({

        options: {
            opacity:   1,
            fineColor: 'rgba(0, 100, 175, 0.55)',
            fineWidth: 0.7,
            boldColor: 'rgba(0, 75, 150, 0.9)',
            boldWidth: 2.0,
            fontColor: 'rgba(0, 55, 135, 1.0)',
            fontFace:  'Arial, Helvetica, sans-serif',
        },

        initialize: function (options) {
            L.setOptions(this, options);
        },

        onAdd: function (map) {
            this._map = map;
            if (!this._container) this._createCanvas();
            map._panes.overlayPane.appendChild(this._container);
            map.on('viewreset move moveend', this._reRender, this);
            this._reRender();
        },

        onRemove: function (map) {
            map.getPanes().overlayPane.removeChild(this._container);
            map.off('viewreset move moveend', this._reRender, this);
        },

        addTo: function (map) { map.addLayer(this); return this; },

        setOpacity: function (opacity) {
            this.options.opacity = opacity;
            if (this._canvas) L.DomUtil.setOpacity(this._canvas, opacity);
            return this;
        },

        getAttribution: function () { return this.options.attribution; },

        _createCanvas: function () {
            this._container = L.DomUtil.create('div', 'leaflet-image-layer');
            this._canvas    = L.DomUtil.create('canvas', '');
            L.DomUtil.addClass(this._canvas, 'leaflet-zoom-hide');
            L.DomUtil.setOpacity(this._canvas, this.options.opacity);
            this._container.appendChild(this._canvas);
            L.extend(this._canvas, {
                onselectstart: L.Util.falseFn,
                onmousemove:   L.Util.falseFn,
            });
        },

        _reRender: function () {
            const map  = this._map;
            const size = map.getSize();
            L.DomUtil.setPosition(this._container, map.containerPointToLayerPoint([0, 0]));
            this._container.style.width  = size.x + 'px';
            this._container.style.height = size.y + 'px';
            this._canvas.width           = size.x;
            this._canvas.height          = size.y;
            this._canvas.style.width     = size.x + 'px';
            this._canvas.style.height    = size.y + 'px';
            this._render();
        },

        _render: function () {
            if (!L.Browser.canvas || !this._map) return;

            const map = this._map;
            const ctx = this._canvas.getContext('2d');
            const W   = this._canvas.width;
            const H   = this._canvas.height;
            ctx.clearRect(0, 0, W, H);

            // Quick cull: skip if GB is not in the current view
            const bounds = map.getBounds();
            const sw = bounds.getSouthWest();
            const ne = bounds.getNorthEast();
            if (ne.lat < 49.0 || sw.lat > 61.5 || ne.lng < -10.0 || sw.lng > 3.5) return;

            // Sample WGS84 grid corners (3×3) to find the visible BNG bounding box
            const sLats = [Math.max(sw.lat, 49.0), (sw.lat+ne.lat)/2, Math.min(ne.lat, 61.5)];
            const sLons = [Math.max(sw.lng,-10.0), (sw.lng+ne.lng)/2, Math.min(ne.lng,  3.5)];
            let eMin = 1e9, eMax = -1e9, nMin = 1e9, nMax = -1e9;
            for (const la of sLats) {
                for (const lo of sLons) {
                    const [e, n] = _wgs84_to_bng(la, lo);
                    if (e < eMin) eMin = e;  if (e > eMax) eMax = e;
                    if (n < nMin) nMin = n;  if (n > nMax) nMax = n;
                }
            }
            eMin = Math.max(eMin, _E_MIN); eMax = Math.min(eMax, _E_MAX);
            nMin = Math.max(nMin, _N_MIN); nMax = Math.min(nMax, _N_MAX);
            if (eMin >= eMax || nMin >= nMax) return;

            // Select grid levels from zoom
            // fineStep: the small interval grid drawn in thin lines
            // boldStep: the large interval grid drawn in thick lines and labelled
            const zoom = map.getZoom();
            let fineStep, boldStep, labelFontSize;
            if (zoom >= 16) {
                // 100m fine, 1km bold, label each 100m square: "NY 123 456"
                fineStep = 100;   boldStep = 1000;  labelFontSize = 9;
            } else if (zoom >= 14) {
                // 100m fine, 1km bold, label each 1km square: "NY 12 45"
                fineStep = 100;   boldStep = 1000;  labelFontSize = 10;
            } else if (zoom >= 11) {
                // 1km fine, 10km bold, label each 10km square: "NY 3 5"
                fineStep = 1000;  boldStep = 10000; labelFontSize = 12;
            } else if (zoom >= 8) {
                // 10km fine, 100km bold, label each 100km square: "NY"
                fineStep = 10000; boldStep = 100000; labelFontSize = 16;
            } else {
                // 100km only, labelled: "NY"
                fineStep = null;  boldStep = 100000; labelFontSize = 16;
            }

            // Performance cap: bail if fine grid would produce too many lines
            if (fineStep && ((eMax - eMin) / fineStep > 300 || (nMax - nMin) / fineStep > 300)) return;

            // Convert BNG (E, N) to canvas pixel via WGS84
            const b2px = (E, N) => {
                const [la, lo] = _bng_to_wgs84(E, N);
                return map.latLngToContainerPoint(L.latLng(la, lo));
            };

            // Draw a grid pass: compute all intersection pixels, then stroke rows and columns
            const drawGrid = (step, color, lineWidth) => {
                const eStart = Math.floor(eMin / step) * step;
                const nStart = Math.floor(nMin / step) * step;
                const eArr = [], nArr = [];
                for (let e = eStart; e <= eMax + step; e += step) {
                    if (e >= _E_MIN && e <= _E_MAX) eArr.push(e);
                }
                for (let n = nStart; n <= nMax + step; n += step) {
                    if (n >= _N_MIN && n <= _N_MAX) nArr.push(n);
                }

                // Pre-compute all grid-intersection pixel positions
                const px = nArr.map(n => eArr.map(e => {
                    try { return b2px(e, n); } catch (_) { return null; }
                }));

                ctx.strokeStyle = color;
                ctx.lineWidth   = lineWidth;

                // Easting lines (constant E, varying N — drawn column by column)
                for (let j = 0; j < eArr.length; j++) {
                    ctx.beginPath();
                    let first = true;
                    for (let i = 0; i < nArr.length; i++) {
                        const pt = px[i][j];
                        if (!pt) { first = true; continue; }
                        first ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y);
                        first = false;
                    }
                    ctx.stroke();
                }

                // Northing lines (constant N, varying E — drawn row by row)
                for (let i = 0; i < nArr.length; i++) {
                    ctx.beginPath();
                    let first = true;
                    for (let j = 0; j < eArr.length; j++) {
                        const pt = px[i][j];
                        if (!pt) { first = true; continue; }
                        first ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y);
                        first = false;
                    }
                    ctx.stroke();
                }
            };

            // Fine grid first so bold grid renders on top
            if (fineStep) drawGrid(fineStep, this.options.fineColor, this.options.fineWidth);
            drawGrid(boldStep, this.options.boldColor, this.options.boldWidth);

            // Labels: placed at the centre of each bold (or 100m at zoom≥16) grid square
            // At zoom≥16 label every 100m square ("NY 123 456"); otherwise label bold squares
            const labelStep = (zoom >= 16) ? fineStep : boldStep;

            ctx.save();
            ctx.font         = `bold ${labelFontSize}px ${this.options.fontFace}`;
            ctx.fillStyle    = this.options.fontColor;
            ctx.strokeStyle  = 'rgba(255,255,255,0.85)';
            ctx.lineWidth    = labelFontSize / 5;
            ctx.lineJoin     = 'round';
            ctx.miterLimit   = 2;
            ctx.textAlign    = 'center';
            ctx.textBaseline = 'middle';

            const lEStart = Math.floor(eMin / labelStep) * labelStep;
            const lNStart = Math.floor(nMin / labelStep) * labelStep;
            for (let eL = lEStart; eL < eMax + labelStep; eL += labelStep) {
                if (eL < _E_MIN || eL >= _E_MAX) continue;
                for (let nL = lNStart; nL < nMax + labelStep; nL += labelStep) {
                    if (nL < _N_MIN || nL >= _N_MAX) continue;
                    try {
                        const pt  = b2px(eL + labelStep/2, nL + labelStep/2);
                        const lbl = _ref(eL, nL, labelStep);
                        ctx.strokeText(lbl, pt.x, pt.y);
                        ctx.fillText(lbl,   pt.x, pt.y);
                    } catch (_) {}
                }
            }
            ctx.restore();
        },
    });
}

export { otm_init_bng_factory };
