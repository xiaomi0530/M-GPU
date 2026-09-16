`timescale 1ns / 1ps

// Neon core: a faceted crystal, segmented halo and four-point stars.
// All shapes are drawn through the triangle interface, in painter's order.
// Internal monitors compensate for gpu_done currently meaning rast_done.

module mgpu_tb;

    localparam H_RES = 640;
    localparam V_RES = 480;
    localparam FB_PIXELS = H_RES * V_RES;

    reg clk = 1'b0;
    reg rst = 1'b1;
    reg start = 1'b0;

    reg [9:0] x0;
    reg [9:0] y0;
    reg [7:0] clor0;

    reg [9:0] x1;
    reg [9:0] y1;
    reg [7:0] clor1;

    reg [9:0] x2;
    reg [9:0] y2;
    reg [7:0] clor2;

    reg [7:0] clear_color    = 8'h00;

    wire busy;
    wire done;

    integer fd;
    integer trace_fd;
    // Image Studio writes this file; +DEMO selects the original neon scene.
    localparam DEFAULT_IMAGE_SCENE = "out/image_scene.tri";
    reg [8191:0] scene_path;
    integer scene_fd;
    integer scene_count;
    integer scene_index;
    integer scene_fields;
    integer scene_ax, scene_ay, scene_bx, scene_by, scene_cx, scene_cy;
    reg [7:0] scene_ca, scene_cb, scene_cc;
    integer i;
    integer triangle_count = 0;
    integer fragment_count = 0;
    integer pixel_count = 0;
    integer full_cycles = 0;
    integer segment;
    integer ox0, oy0, ox1, oy1, ix0, iy0, ix1, iy1;
    real angle0, angle1;
    reg [7:0] tint0, tint1;

    // Observe exactly the clock edges used by FIFO writes and framebuffer writes.
    always @(posedge clk) begin
        if (!rst) begin
            if (u_mgpu.fifo_rs_wen && !u_mgpu.fifo_rs_full)
                fragment_count <= fragment_count + 1;
            if (u_mgpu.fifo_rs_full)
                full_cycles <= full_cycles + 1;
            if (u_mgpu.shad_done) begin
                if ((^{u_mgpu.pixel_x, u_mgpu.pixel_y,
                       u_mgpu.pixel_R, u_mgpu.pixel_G, u_mgpu.pixel_B}) === 1'bx)
                    $fatal(1, "Unknown pixel output");
                if (u_mgpu.pixel_x >= H_RES || u_mgpu.pixel_y >= V_RES)
                    $fatal(1, "Pixel outside framebuffer");
                pixel_count <= pixel_count + 1;
                // Decimal $time is in this module's ns units (not %t's ps).
                $fwrite(trace_fd, "P %0d %0d %0d %0d %02x\n", $time,
                        triangle_count + 1, u_mgpu.pixel_x, u_mgpu.pixel_y,
                        {u_mgpu.pixel_R,u_mgpu.pixel_G,u_mgpu.pixel_B});
                // Batch disk flushes for live viewing without flushing every pixel.
                if ((pixel_count % 256) == 255)
                    $fflush(trace_fd);
            end
        end
    end

    function [7:0] palette;
        input integer index;
        begin
            case (index % 8)
                0: palette = 8'h1F; // cyan
                1: palette = 8'h13; // azure
                2: palette = 8'h83; // violet
                3: palette = 8'hE3; // magenta
                4: palette = 8'hE9; // coral
                5: palette = 8'hFC; // gold
                6: palette = 8'h9C; // lime
                7: palette = 8'h1D; // mint
            endcase
        end
    endfunction

    task draw_triangle;
        input integer ax, ay, bx, by, cx, cy;
        input [7:0] ca, cb, cc;
        integer before_fragments;
        begin
            if (ax < 0 || ax >= H_RES || bx < 0 || bx >= H_RES ||
                cx < 0 || cx >= H_RES || ay < 0 || ay >= V_RES ||
                by < 0 || by >= V_RES || cy < 0 || cy >= V_RES)
                $fatal(1, "Invalid test triangle coordinates");
            if ((bx-ax)*(cy-ay) == (by-ay)*(cx-ax))
                $fatal(1, "Zero-area test triangle");
            before_fragments = fragment_count;
            // Drive away from the active edge; reverse alternating triangles
            // together with their colors to exercise both vertex windings.
            @(negedge clk);
            x0 = ax; y0 = ay; clor0 = ca;
            if (triangle_count % 2 == 0) begin
                x1 = bx; y1 = by; clor1 = cb;
                x2 = cx; y2 = cy; clor2 = cc;
            end else begin
                x1 = cx; y1 = cy; clor1 = cc;
                x2 = bx; y2 = by; clor2 = cb;
            end
            start = 1'b1;
            $fwrite(trace_fd, "B %0d %0d %0d %0d %0d %0d %0d %0d\n",
                    $time, triangle_count + 1, x0,y0,x1,y1,x2,y2);
            $fflush(trace_fd);
            @(negedge clk);
            start = 1'b0;
            wait (done === 1'b1);
            // Rasterizer completion does not imply the FIFO/shader is drained.
            // Check on falling edges, after nonblocking writes have committed.
            @(negedge clk);
            while (!u_mgpu.fifo_rs_empty || pixel_count != fragment_count)
                @(negedge clk);
            if (fragment_count == before_fragments)
                $fatal(1, "Triangle produced no fragments");
            triangle_count = triangle_count + 1;
            $fwrite(trace_fd, "E %0d %0d\n", $time, triangle_count);
            $fflush(trace_fd);
            $display("Triangle %0d complete: %0d pixels", triangle_count,
                     fragment_count - before_fragments);
        end
    endtask

    task star;
        input integer sx, sy, size;
        input [7:0] tint;
        begin
            draw_triangle(sx,sy-size, sx+3,sy, sx,sy, tint,tint,8'hFF);
            draw_triangle(sx+size,sy, sx,sy+3, sx,sy, tint,tint,8'hFF);
            draw_triangle(sx,sy+size, sx-3,sy, sx,sy, tint,tint,8'hFF);
            draw_triangle(sx-size,sy, sx,sy-3, sx,sy, tint,tint,8'hFF);
        end
    endtask

    // Fail instead of hanging if a handshake or completion condition breaks.
    initial begin
        repeat (100000000) @(posedge clk);
        $fatal(1, "Timeout: triangles=%0d fragments=%0d pixels=%0d",
               triangle_count, fragment_count, pixel_count);
    end

    // 100 MHz-style clock for simulation: 10 ns period.
    always #5 clk = ~clk;

    mgpu #(
        .H_RES(H_RES),
        .V_RES(V_RES),
        .FB_PIXELS(FB_PIXELS),
        .FB_ADDR_W(19)
    ) u_mgpu (
        .clk(clk),
        .rst(rst),
        .start(start),
        .x0(x0),
        .y0(y0),
        .x1(x1),
        .y1(y1),
        .x2(x2),
        .y2(y2),
        .clor0(clor0),
        .clor1(clor1),
        .clor2(clor2),
        .clear_color(clear_color),
        .gpu_busy(busy),
        .gpu_done(done)
    );

    initial begin
        $display("MGPU neon core simulation started.");
        trace_fd = $fopen("out/framebuffer.trace", "w");
        if (trace_fd == 0)
            $fatal(1, "Could not open out/framebuffer.trace; create out/ first");
        $fwrite(trace_fd, "MGPU_TRACE 1 %0d %0d %02x ns\n",
                H_RES, V_RES, clear_color);
        $fflush(trace_fd);
        x0 = 0; y0 = 0; clor0 = 0;
        x1 = 0; y1 = 0; clor1 = 0;
        x2 = 0; y2 = 0; clor2 = 0;
        repeat (5) @(negedge clk);
        rst = 1'b0;

        scene_fd = 0;
        if (!$test$plusargs("DEMO")) begin
            if ($value$plusargs("IMAGE_SCENE=%s", scene_path)) begin
                scene_fd = $fopen(scene_path, "r");
                if (scene_fd == 0) $fatal(1, "Cannot open requested IMAGE_SCENE");
            end else begin
                scene_fd = $fopen(DEFAULT_IMAGE_SCENE, "r");
            end
        end
        if (scene_fd != 0) begin
            scene_fields = $fscanf(scene_fd, "%d\n", scene_count);
            if (scene_fields != 1 || scene_count < 0 || scene_count > 160002)
                $fatal(1, "Invalid image scene triangle count");
            $display("Drawing image scene: %0d triangles", scene_count);
            for (scene_index = 0; scene_index < scene_count; scene_index = scene_index + 1) begin
                scene_fields = $fscanf(scene_fd, "%d %d %d %d %d %d %h %h %h\n",
                    scene_ax,scene_ay,scene_bx,scene_by,scene_cx,scene_cy,
                    scene_ca,scene_cb,scene_cc);
                if (scene_fields != 9) $fatal(1, "Invalid triangle %0d", scene_index);
                draw_triangle(scene_ax,scene_ay,scene_bx,scene_by,scene_cx,scene_cy,
                              scene_ca,scene_cb,scene_cc);
            end
            $fclose(scene_fd);
        end else begin

        // Dark angular backdrop. Later triangles deliberately overlap it.
        draw_triangle(320,18, 610,240, 320,462, 8'h01,8'h05,8'h21);
        draw_triangle(320,18, 320,462, 30,240, 8'h01,8'h21,8'h04);

        // Sixteen separated trapezoids, each made from two triangles.
        // Real trigonometry is testbench-only; the GPU receives integer vertices.
        for (segment = 0; segment < 16; segment = segment + 1) begin
            angle0 = (segment * 22.5 - 90.0 + 2.0) * 3.141592653589793 / 180.0;
            angle1 = (segment * 22.5 - 90.0 + 20.5) * 3.141592653589793 / 180.0;
            ox0 = 320 + $rtoi(208.0 * $cos(angle0));
            oy0 = 240 + $rtoi(208.0 * $sin(angle0));
            ox1 = 320 + $rtoi(208.0 * $cos(angle1));
            oy1 = 240 + $rtoi(208.0 * $sin(angle1));
            ix0 = 320 + $rtoi(190.0 * $cos(angle0));
            iy0 = 240 + $rtoi(190.0 * $sin(angle0));
            ix1 = 320 + $rtoi(190.0 * $cos(angle1));
            iy1 = 240 + $rtoi(190.0 * $sin(angle1));
            tint0 = palette(segment / 2);
            tint1 = palette(segment / 2 + 1);
            draw_triangle(ox0,oy0, ox1,oy1, ix1,iy1, tint0,tint1,8'hFF);
            draw_triangle(ox0,oy0, ix1,iy1, ix0,iy0, tint0,8'hFF,tint0);
        end

        // Floating crystal: hard facet boundaries plus interpolated interiors.
        draw_triangle(320,94, 216,205, 320,176, 8'hFF,8'h1F,8'h7F);
        draw_triangle(320,94, 320,176, 424,205, 8'hFF,8'h7F,8'h83);
        draw_triangle(216,205, 265,320, 320,244, 8'h1F,8'h12,8'h5F);
        draw_triangle(216,205, 320,244, 320,176, 8'h1F,8'hFF,8'h7F);
        draw_triangle(320,176, 320,244, 424,205, 8'hBF,8'hE3,8'h83);
        draw_triangle(424,205, 320,244, 375,320, 8'h83,8'hE3,8'hE9);
        draw_triangle(265,320, 320,386, 320,244, 8'h13,8'hFF,8'h5F);
        draw_triangle(320,244, 320,386, 375,320, 8'hE3,8'hFF,8'hE9);

        star(320,94, 16,8'h1F);
        star(88,102, 18,8'h1F);
        star(554,126, 13,8'hE3);
        star(92,361, 12,8'h9C);
        star(548,374, 20,8'hFC);

        // RGB calibration chips: saturated constant-color triangle pairs.
        for (segment = 0; segment < 8; segment = segment + 1) begin
            tint0 = palette(segment);
            draw_triangle(244+segment*20,464, 258+segment*20,464,
                          258+segment*20,470, tint0,tint0,tint0);
            draw_triangle(244+segment*20,464, 258+segment*20,470,
                          244+segment*20,470, tint0,tint0,tint0);
        end

        if (full_cycles == 0)
            $fatal(1, "Scene did not exercise FIFO backpressure");
        end
        $display("PASS: %0d triangles, %0d fragments, %0d writes, %0d FIFO-full cycles",
                 triangle_count, fragment_count, pixel_count, full_cycles);

        fd = $fopen("out/framebuffer.hex", "w");
        if (fd == 0) begin
            $fatal(1, "Could not open out/framebuffer.hex; create out/ first");
        end

        for (i = 0; i < FB_PIXELS; i = i + 1) begin
            $fwrite(fd, "%02x\n", u_mgpu.frame_buffer[i]);
        end

        $fclose(fd);
        $fwrite(trace_fd, "D %0d %0d %0d\n", $time, triangle_count, pixel_count);
        $fflush(trace_fd);
        $fclose(trace_fd);
        $display("Framebuffer dumped to out/framebuffer.hex");
        $display("Live/replay viewer: python tools/view_framebuffer.py --live");
        $display("Run: python tools/view_framebuffer.py out/framebuffer.hex");

        $finish;
    end

endmodule
