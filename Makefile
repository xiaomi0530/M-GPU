PYTHON ?= python
VIVADO ?= vivado

.PHONY: all run image gui live simulate-image test format-check clean milkfrog-sim milkfrog-bit milkfrog-crosscheck milkfrog-package milkfrog-orbit-assets milkfrog-orbit-preview milkfrog-orbit-sim milkfrog-orbit-bit milkfrog-orbit-crosscheck milkfrog-orbit-package milkfrog-v1-assets milkfrog-v1-preview milkfrog-v1-sim milkfrog-v1-bit milkfrog-v1-crosscheck milkfrog-v1-package milkfrog-v2-assets milkfrog-v2-preview milkfrog-v2-sim milkfrog-v2-bit milkfrog-v2-crosscheck milkfrog-v2-package milkfrog-check-releases
all: image
run:
	$(PYTHON) tools/top_simulation.py --output out/simulation
image: run
	$(PYTHON) tools/view_framebuffer.py out/simulation/framebuffer.hex
gui:
	$(PYTHON) tools/view_framebuffer.py
live:
	$(PYTHON) tools/view_framebuffer.py --live
simulate-image:
	$(PYTHON) tools/top_simulation.py --scene out/image_scene.tri --output out/studio_image
test:
	$(PYTHON) tools/run_tests.py --python
format-check:
	$(PYTHON) tools/format_hdl.py --check
milkfrog-sim:
	$(PYTHON) tools/run_milkfrog_board.py --frames 542 --video --controls
milkfrog-bit:
	$(VIVADO) -mode batch -source tools/build_milkfrog.tcl -tclargs assets/milkfrog/v1_fixed/rom out/milkfrog_board/build
milkfrog-crosscheck:
	$(PYTHON) tools/run_milkfrog_board.py --frames 542 --video --controls --reuse-capture --crosscheck
milkfrog-package:
	$(PYTHON) tools/package_milkfrog.py
milkfrog-orbit-assets:
	$(PYTHON) -X utf8 tools/build_milkfrog_orbit.py
	$(PYTHON) tools/build_milkfrog_rom.py --input-dir assets/milkfrog/v2_orbit/animation --output-dir assets/milkfrog/v2_orbit/rom --review-dir out/milkfrog_orbit_v2/board_reference --order-caches 26 --order-entry-budget 131072 --order-workers 4 --order-iterations 4 --order-reference-frames 0,40,80,123,166,210,250,290,332,365,390,396,402,405,407,408,409,410,411,412,415,419,435,470,505,540 --dedicated-order-frames 408,409,410,411
milkfrog-orbit-preview:
	$(PYTHON) tools/preview_milkfrog_rom.py --animation-dir assets/milkfrog/v2_orbit/animation --rom-dir assets/milkfrog/v2_orbit/rom --projection out/milkfrog_orbit_v2/board_reference/projection.npz --output out/milkfrog_orbit_v2/painter_verified --workers 4 --compare-sort
milkfrog-orbit-sim:
	$(PYTHON) tools/run_milkfrog_board.py --rom-dir assets/milkfrog/v2_orbit/rom --output out/milkfrog_orbit_v2/rtl --frames 542 --controls --video
milkfrog-orbit-bit:
	$(VIVADO) -mode batch -source tools/build_milkfrog.tcl -tclargs assets/milkfrog/v2_orbit/rom out/milkfrog_orbit_v2/build
milkfrog-orbit-crosscheck:
	$(PYTHON) tools/run_milkfrog_board.py --rom-dir assets/milkfrog/v2_orbit/rom --output out/milkfrog_orbit_v2/rtl --frames 542 --controls --video --reuse-capture --crosscheck --fpga-init-proof out/milkfrog_orbit_v2/build/register_init.rpt
milkfrog-orbit-package:
	$(PYTHON) tools/review_milkfrog_orbit.py
	$(PYTHON) tools/milkfrog_orbit_video.py
	$(PYTHON) tools/package_milkfrog_orbit.py
# Equal-status version entry points. The original names remain compatibility aliases.
milkfrog-v1-assets:
	$(PYTHON) -X utf8 tools/milkfrog_animation.py
	$(PYTHON) tools/build_milkfrog_rom.py --input-dir assets/milkfrog/v1_fixed/animation --output-dir assets/milkfrog/v1_fixed/rom --review-dir out/naiwa/board_reference --order-caches 26 --order-entry-budget 131072 --order-workers 4 --order-iterations 3
milkfrog-v1-preview:
	$(PYTHON) tools/preview_milkfrog_rom.py --animation-dir assets/milkfrog/v1_fixed/animation --rom-dir assets/milkfrog/v1_fixed/rom --projection out/naiwa/board_reference/projection.npz --output out/naiwa/painter_verified --workers 4 --compare-sort
milkfrog-v1-sim: milkfrog-sim
milkfrog-v1-bit: milkfrog-bit
milkfrog-v1-crosscheck: milkfrog-crosscheck
milkfrog-v1-package: milkfrog-package
milkfrog-v2-assets: milkfrog-orbit-assets
milkfrog-v2-preview: milkfrog-orbit-preview
milkfrog-v2-sim: milkfrog-orbit-sim
milkfrog-v2-bit: milkfrog-orbit-bit
milkfrog-v2-crosscheck: milkfrog-orbit-crosscheck
milkfrog-v2-package: milkfrog-orbit-package
milkfrog-check-releases:
	$(PYTHON) tools/check_milkfrog_releases.py
clean:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/clean.ps1
