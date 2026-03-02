const ImageLightbox = (() => {
    const IMAGE_SELECTOR = "article img[src*='media'], .prose img";
    const EXCLUDE_SELECTOR = '.emoji, .icon, [data-ignore-lightbox]';

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    class Lightbox {
        constructor(images) {
            this.images = images;
            this.currentIndex = 0;
            this.scale = 1;
            this.offset = { x: 0, y: 0 };
            this.dragStart = null;
            this.isDragging = false;

            this._bindGlobalHandlers();
            this._buildDom();
        }

        _buildDom() {
            this.overlay = document.createElement('div');
            this.overlay.id = 'imageLightboxOverlay';
            this.overlay.innerHTML = 
                <div class="ilb-backdrop"></div>
                <div class="ilb-window" role="dialog" aria-modal="true" aria-label="РџСЂРѕСЃРјРѕС‚СЂ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ">
                    <button class="ilb-close" aria-label="Р—Р°РєСЂС‹С‚СЊ (Esc)">Г—</button>
                    <div class="ilb-stage">
                        <img class="ilb-image" alt="РР·РѕР±СЂР°Р¶РµРЅРёРµ" draggable="false">
                    </div>
                    <div class="ilb-toolbar">
                        <div class="ilb-counter"><span id="ilbIndex">1</span>/<span id="ilbTotal">1</span></div>
                        <div class="ilb-controls">
                            <button class="ilb-btn" data-action="prev" aria-label="РџСЂРµРґС‹РґСѓС‰РµРµ (в†ђ)">в—Ђ</button>
                            <button class="ilb-btn" data-action="next" aria-label="РЎР»РµРґСѓСЋС‰РµРµ (в†’)">в–¶</button>
                            <button class="ilb-btn" data-action="zoom-in" aria-label="РџСЂРёР±Р»РёР·РёС‚СЊ (+)">+</button>
                            <button class="ilb-btn" data-action="zoom-out" aria-label="РћС‚РґР°Р»РёС‚СЊ (-)">в€’</button>
                            <button class="ilb-btn" data-action="zoom-reset" aria-label="РЎР±СЂРѕСЃРёС‚СЊ (0)">1:1</button>
                            <a class="ilb-btn" data-action="download" aria-label="РЎРєР°С‡Р°С‚СЊ" download>в¤“</a>
                        </div>
                    </div>
                </div>;

            document.body.appendChild(this.overlay);

            this.windowEl = this.overlay.querySelector('.ilb-window');
            this.stageEl = this.overlay.querySelector('.ilb-stage');
            this.imageEl = this.overlay.querySelector('.ilb-image');
            this.closeBtn = this.overlay.querySelector('.ilb-close');
            this.counterIndex = this.overlay.querySelector('#ilbIndex');
            this.counterTotal = this.overlay.querySelector('#ilbTotal');
            this.controls = this.overlay.querySelector('.ilb-controls');
            this.downloadBtn = this.controls.querySelector('[data-action="download"]');

            this.closeBtn.addEventListener('click', () => this.hide());
            this.overlay.addEventListener('click', (event) => {
                if (event.target.closest('.ilb-window') && !event.target.classList.contains('ilb-backdrop')) {
                    return;
                }
                this.hide();
            });

            this.controls.addEventListener('click', (event) => {
                const button = event.target.closest('[data-action]');
                if (!button) return;
                event.preventDefault();
                const action = button.dataset.action;
                switch (action) {
                    case 'prev':
                        this.prev();
                        break;
                    case 'next':
                        this.next();
                        break;
                    case 'zoom-in':
                        this.zoom(0.2);
                        break;
                    case 'zoom-out':
                        this.zoom(-0.2);
                        break;
                    case 'zoom-reset':
                        this.resetZoom();
                        break;
                    case 'download':
                        break;
                }
            });

            this.stageEl.addEventListener('wheel', (event) => {
                event.preventDefault();
                this.zoom(event.deltaY < 0 ? 0.2 : -0.2);
            }, { passive: false });

            this.stageEl.addEventListener('mousedown', (event) => {
                if (event.button !== 0) return;
                this.isDragging = true;
                this.windowEl.classList.add('is-dragging');
                this.dragStart = { x: event.clientX - this.offset.x, y: event.clientY - this.offset.y };
                document.addEventListener('mousemove', this._onDragMove);
                document.addEventListener('mouseup', this._onDragEnd);
            });

            this._injectStyles();
        }

        _bindGlobalHandlers() {
            this._onKeydown = (event) => {
                if (!this.isVisible()) return;
                switch (event.key) {
                    case 'ArrowRight':
                    case 'd':
                    case 'D':
                        this.next();
                        break;
                    case 'ArrowLeft':
                    case 'a':
                    case 'A':
                        this.prev();
                        break;
                    case '+':
                    case '=':
                        this.zoom(0.2);
                        break;
                    case '-':
                    case '_':
                        this.zoom(-0.2);
                        break;
                    case '0':
                        this.resetZoom();
                        break;
                    case 'Escape':
                        this.hide();
                        break;
                }
            };

            this._onDragMove = (event) => {
                if (!this.isDragging) return;
                this.offset.x = event.clientX - this.dragStart.x;
                this.offset.y = event.clientY - this.dragStart.y;
                this._applyTransform();
            };

            this._onDragEnd = () => {
                this.isDragging = false;
                this.windowEl.classList.remove('is-dragging');
                document.removeEventListener('mousemove', this._onDragMove);
                document.removeEventListener('mouseup', this._onDragEnd);
            };

            document.addEventListener('keydown', this._onKeydown);
        }

        _injectStyles() {
            if (document.getElementById('imageLightboxStyles')) return;
            const style = document.createElement('style');
            style.id = 'imageLightboxStyles';
            style.textContent = 
                body.ilb-lock { overflow: hidden; }
                #imageLightboxOverlay { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(15, 15, 20, .85); backdrop-filter: blur(8px); opacity: 0; pointer-events: none; transition: opacity .25s ease; z-index: 9999; }
                #imageLightboxOverlay.is-active { opacity: 1; pointer-events: auto; }
                #imageLightboxOverlay .ilb-backdrop { position:absolute; inset:0; }
                #imageLightboxOverlay .ilb-window { position:relative; display:flex; flex-direction:column; gap:12px; max-width:92vw; max-height:92vh; }
                #imageLightboxOverlay .ilb-close { position:absolute; top:-18px; right:-18px; width:36px; height:36px; border-radius:50%; border:none; background:#ef4444; color:#fff; font-size:22px; cursor:pointer; box-shadow:0 10px 25px rgba(239,68,68,.45); }
                #imageLightboxOverlay .ilb-close:hover { background:#dc2626; }
                #imageLightboxOverlay .ilb-stage { position:relative; width:min(92vw,1200px); height:min(70vh,800px); background:rgba(255,255,255,.05); border-radius:18px; overflow:hidden; display:flex; align-items:center; justify-content:center; box-shadow:0 20px 60px rgba(0,0,0,.55); border:1px solid rgba(255,255,255,.08); }
                #imageLightboxOverlay .ilb-image { max-width:100%; max-height:100%; transition:transform .2s ease; cursor:grab; user-select:none; }
                #imageLightboxOverlay .is-dragging .ilb-image { cursor:grabbing; }
                #imageLightboxOverlay .ilb-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:12px 16px; border-radius:14px; background:rgba(15,23,42,.82); color:#fff; box-shadow:0 14px 34px rgba(15,23,42,.45); backdrop-filter:blur(6px); }
                #imageLightboxOverlay .ilb-controls { display:flex; align-items:center; gap:8px; }
                #imageLightboxOverlay .ilb-btn { width:38px; height:38px; border-radius:10px; border:1px solid rgba(255,255,255,.25); background:rgba(148,163,184,.18); color:#fff; font-size:16px; font-weight:600; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all .2s ease; text-decoration:none; }
                #imageLightboxOverlay .ilb-btn:hover { background:rgba(148,163,184,.35); }
                #imageLightboxOverlay .ilb-counter { font-weight:600; }
                @media (max-width:768px) {
                    #imageLightboxOverlay .ilb-window { gap:10px; }
                    #imageLightboxOverlay .ilb-stage { height:60vh; }
                    #imageLightboxOverlay .ilb-toolbar { flex-direction:column; align-items:stretch; gap:12px; }
                    #imageLightboxOverlay .ilb-controls { flex-wrap:wrap; }
                }
            ;
            document.head.appendChild(style);
        }

        show(index) {
            this.currentIndex = clamp(index, 0, this.images.length - 1);
            this._render();
            this.overlay.classList.add('is-active');
            document.body.classList.add('ilb-lock');
        }

        hide() {
            this.overlay.classList.remove('is-active');
            document.body.classList.remove('ilb-lock');
            this.resetZoom();
            setTimeout(() => {
                this.imageEl.removeAttribute('src');
            }, 200);
        }

        next() {
            this.currentIndex = (this.currentIndex + 1) % this.images.length;
            this._render();
        }

        prev() {
            this.currentIndex = (this.currentIndex - 1 + this.images.length) % this.images.length;
            this._render();
        }

        zoom(delta) {
            this.scale = clamp(this.scale + delta, 0.35, 5);
            this._applyTransform();
        }

        resetZoom() {
            this.scale = 1;
            this.offset = { x: 0, y: 0 };
            this._applyTransform();
        }

        isVisible() {
            return this.overlay.classList.contains('is-active');
        }

        _render() {
            const image = this.images[this.currentIndex];
            if (!image) return;

            const src = image.currentSrc || image.src;
            this.imageEl.src = src;
            this.imageEl.alt = image.alt || '';
            this.downloadBtn.href = src;

            this.counterIndex.textContent = String(this.currentIndex + 1);
            this.counterTotal.textContent = String(this.images.length);

            this.resetZoom();
        }

        _applyTransform() {
            this.imageEl.style.transform = 	ranslate3d(px, px, 0) scale();
        }
    }

    const init = () => {
        const candidates = Array.from(document.querySelectorAll(IMAGE_SELECTOR)).filter((img) => !img.closest(EXCLUDE_SELECTOR));
        if (!candidates.length) return null;

        const lightbox = new Lightbox(candidates);

        candidates.forEach((img, index) => {
            img.style.cursor = 'zoom-in';
            img.addEventListener('click', (event) => {
                event.preventDefault();
                lightbox.show(index);
            });
        });

        return lightbox;
    };

    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    ImageLightbox.init();
});
