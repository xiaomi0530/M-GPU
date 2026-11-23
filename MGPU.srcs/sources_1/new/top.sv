module top #(
    parameter int BUTTON_FILTER_BITS = 16,
    parameter int GPU_CLK_DIV_LOG2 = 0,
    parameter int LOGO_HOLD_MS = 7000,
    parameter int STAGE_HOLD_MS = 4000,
    parameter int CUBE_HOLD_MS = 0,
    parameter int TARGET_FPS = 60,
    parameter int START_FRAME = 0,
    parameter int START_LOGO_FRAME = 0,
    parameter int H_RES = 320,
    parameter int V_RES = 240,
    parameter int CUBE_HALF_SIZE = 96
)(
    input logic CLK100MHZ,
    input logic CPU_RESETN,
    input logic BTNU,
    output logic [3:0] VGA_R,
    output logic [3:0] VGA_G,
    output logic [3:0] VGA_B,
    output logic VGA_HS,
    output logic VGA_VS
);

    typedef enum logic [3:0]{
        FETCH,
        LOAD,
        ISSUE,
        WAIT_GPU,
        ADVANCE,
        HOLD,
        CLEAR_ISSUE,
        CLEAR_WAIT,
        INDEX,
        PRESENT,
        SWAP_WAIT,
        FETCH_B
    } state_t;
    state_t state;

    localparam int GPU_HZ = (GPU_CLK_DIV_LOG2 == 0) ? 40000000 : 100000000 / (1 << GPU_CLK_DIV_LOG2);
    localparam int COMMAND_COUNT = 862;
    localparam int FRAME_COUNT = 512;
    localparam int LOGO_FRAME_COUNT = 420;
    localparam int LOGO_GROUP_COUNT = 25;
    localparam int MODEL_GROUP_COUNT = 9;
    localparam int MODEL_KEY_COUNT = 64;
    localparam int MODEL_SLOT_COUNT = MODEL_KEY_COUNT * MODEL_GROUP_COUNT;
    localparam int ROM_FRAME_COUNT = FRAME_COUNT + LOGO_FRAME_COUNT;
    localparam int MATRIX_SLOT_COUNT = MODEL_SLOT_COUNT + LOGO_FRAME_COUNT * LOGO_GROUP_COUNT;
    localparam int MATRIX_COUNT = 5185;
    localparam int ORDER_COUNT = 157708;
    localparam int INTRO_NEXT_FRAME = 25;
    localparam int ORDER_STRIDE = 512;
    localparam int FRAME_TICKS = (TARGET_FPS > 0) ? GPU_HZ / TARGET_FPS : 1;
    localparam int LOGO_TICKS = (GPU_HZ / 1000) * LOGO_HOLD_MS;

    logic gpu_clk;
    logic gpu_clk_locked;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic [3:0] gpu_reset_pipe = 4'b1111;
    logic gpu_reset_request;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic [3:0] reset_pipe = 4'b1111;
    logic vga_rst = 1'b1;
    logic rst = 1'b1;
    (* ASYNC_REG = "TRUE" *) logic [1:0] button_sync;
    logic [BUTTON_FILTER_BITS-1:0] button_count;
    logic button_level;
    logic button_press;
    logic [31:0] frame_elapsed;
    logic [31:0] boot_elapsed;
    logic paused;
    logic [17:0] command_address;
    logic demo_start;
    logic demo_clear;
    logic demo_present;
    logic saw_busy;
    logic gpu_busy;
    logic gpu_done;
    logic gpu_error;
    logic present_done;
    logic [9:0] gpu_x0;
    logic [9:0] gpu_y0;
    logic [9:0] gpu_x1;
    logic [9:0] gpu_y1;
    logic [9:0] gpu_x2;
    logic [9:0] gpu_y2;
    logic [7:0] gpu_c0;
    logic [7:0] gpu_c1;
    logic [7:0] gpu_c2;
    logic signed [17:0] gpu_vx0;
    logic signed [17:0] gpu_vy0;
    logic signed [17:0] gpu_vz0;
    logic signed [17:0] gpu_vx1;
    logic signed [17:0] gpu_vy1;
    logic signed [17:0] gpu_vz1;
    logic signed [17:0] gpu_vx2;
    logic signed [17:0] gpu_vy2;
    logic signed [17:0] gpu_vz2;
    logic logo_active;
    logic [1:0] scene;
    logic [$clog2(FRAME_COUNT)-1:0] animation_frame;
    logic [$clog2(LOGO_FRAME_COUNT)-1:0] logo_frame;
    logic [$clog2(ROM_FRAME_COUNT)-1:0] scene_frame;
    logic [17:0] studio_index;
    logic studio_finished;
    (* rom_style="block" *) logic [185:0] commands[0:COMMAND_COUNT-1];
    logic [4:0] command_group[0:COMMAND_COUNT-1];
    logic [185:0] command_data;
    (* rom_style="block" *) logic [9:0] draw_order[0:ORDER_COUNT-1];
    logic [8:0] frame_counts[0:ROM_FRAME_COUNT-1];
    logic [$clog2(ORDER_COUNT)-1:0] frame_offsets[0:ROM_FRAME_COUNT-1];
    (* rom_style="block" *) logic [287:0] matrices[0:MATRIX_COUNT-1];
    logic [$clog2(MATRIX_COUNT)-1:0] matrix_indices[0:MATRIX_SLOT_COUNT-1];
    logic [287:0] matrix_data;
    logic [287:0] matrix_raw;
    logic [287:0] matrix_first;
    logic [9:0] order_data;
    logic [$clog2(ORDER_COUNT)-1:0] order_address;
    logic [$clog2(MODEL_KEY_COUNT)-1:0] matrix_key;
    logic [$clog2(MODEL_KEY_COUNT)-1:0] matrix_next_key;
    logic [$clog2(
MATRIX_SLOT_COUNT
)-1:0] matrix_slot;
    logic [$clog2(MATRIX_COUNT)-1:0] matrix_address;
    logic [8:0] frame_count;

    gpu_clock

    #(
        .GPU_CLK_DIV_LOG2 (GPU_CLK_DIV_LOG2)
    )
    u_gpu_clock(
        .clk     (CLK100MHZ     ),
        .rst     (!CPU_RESETN   ),
        .gpu_clk (gpu_clk       ),
        .locked  (gpu_clk_locked)
    );

    assign gpu_reset_request = !CPU_RESETN || !gpu_clk_locked;
    always_ff@(posedge CLK100MHZ or posedge gpu_reset_request)begin
        if(gpu_reset_request) reset_pipe <= 4'b1111;
        else reset_pipe <= {reset_pipe[2:0], 1'b0};
    end
    always_ff@(posedge CLK100MHZ) vga_rst <= reset_pipe[3];

    always_ff@(posedge gpu_clk or posedge gpu_reset_request)begin
        if(gpu_reset_request) gpu_reset_pipe <= 4'b1111;
        else gpu_reset_pipe <= {gpu_reset_pipe[2:0], 1'b0};
    end
    always_ff@(posedge gpu_clk) rst <= gpu_reset_pipe[3];

    always_ff@(posedge gpu_clk)begin
        if(rst)begin
            button_sync <= 2'b00;
            button_count <= 0;
            button_level <= 1'b0;
            button_press <= 1'b0;
        end else begin
            button_sync <= {button_sync[0], BTNU};
            button_press <= 1'b0;
            if(button_sync[1] == button_level)begin
                button_count <= 0;
            end else if(&button_count)begin
                button_level <= button_sync[1];
                button_press <= button_sync[1];
                button_count <= 0;
            end else begin
                button_count <= button_count + 1'b1;
            end
        end
    end

    assign scene = logo_active ? 2'd0 : 2'd2;
    assign scene_frame = logo_active ? FRAME_COUNT + logo_frame : animation_frame;
    assign studio_index = command_address;
    assign studio_finished = (state == HOLD);
`ifdef STUDIO_SIMULATION
    logic studio_mode;
    logic [17:0] studio_count;
    logic [83:0] studio_data;
    studio_triangle_source u_studio_source (
        .clk    (gpu_clk     ),
        .index  (studio_index),
        .data   (studio_data ),
        .active (studio_mode ),
        .count  (studio_count)
    );
`else
    logic studio_mode;
    assign studio_mode = 1'b0;
    logic [17:0] studio_count;
    assign studio_count = 0;
    logic [83:0] studio_data;
    assign studio_data = 0;
`endif
    assign order_address = frame_offsets[scene_frame] + command_address;
    assign matrix_key = animation_frame >> 3;
    assign matrix_next_key = (matrix_key == MODEL_KEY_COUNT - 1) ? 0 : matrix_key + 1'b1;
    assign matrix_slot = logo_active ? MODEL_SLOT_COUNT + logo_frame * LOGO_GROUP_COUNT + command_group[order_data] :
        ((state == FETCH_B) ? matrix_next_key : matrix_key) * MODEL_GROUP_COUNT + command_group[order_data] - 16;
    assign matrix_address = matrix_indices[matrix_slot];
    assign frame_count = frame_counts[scene_frame];
`ifndef SYNTHESIS
    logic [59:0] reference_pixels[0:ROM_FRAME_COUNT*ORDER_STRIDE-1];
    logic [59:0] reference_data;
    always_ff@(posedge gpu_clk) reference_data <= reference_pixels[scene_frame*ORDER_STRIDE+command_address];
`endif
    function [287:0] interpolate_matrix;
        input [287:0] first, second;
        input [2:0] fraction;
        logic signed [18:0] a;
        logic signed [18:0] b;
        logic signed [18:0] difference;
        logic signed [22:0] product;
        logic signed [22:0] value;
        integer i;
        begin
            for(i = 0; i < 16; i = i + 1)begin
                a = $signed(first[i*18+:18]);
                b = $signed(second[i*18+:18]);
                difference = b - a;
                product = difference * $signed({1'b0, fraction});
                value = a + (product >>> 3);
                interpolate_matrix[i*18+:18] = value[17:0];
            end
        end
    endfunction
    always_ff@(posedge gpu_clk)begin
        order_data <= draw_order[order_address];
        if(order_data < COMMAND_COUNT) command_data <= commands[order_data];
        matrix_raw <= matrices[matrix_address];
        if(state == FETCH_B) matrix_first <= matrix_raw;
        if(state == LOAD)
            matrix_data <= interpolate_matrix(matrix_first, matrix_raw, logo_active ? 3'd0 : animation_frame[2:0]);
    end
    always_ff@(posedge gpu_clk)begin
        if(rst)begin
            state <= CLEAR_ISSUE;
            command_address <= 0;
            animation_frame <= START_FRAME;
            frame_elapsed <= 0;
            paused <= 1'b0;
            logo_active <= LOGO_HOLD_MS > 0;
            logo_frame <= START_LOGO_FRAME;
            boot_elapsed <= 0;
            demo_start <= 1'b0;
            demo_clear <= 1'b0;
            demo_present <= 1'b0;
            saw_busy <= 1'b0;
            gpu_x0 <= 0;
            gpu_y0 <= 0;
            gpu_x1 <= 0;
            gpu_y1 <= 0;
            gpu_x2 <= 0;
            gpu_y2 <= 0;
            gpu_c0 <= 0;
            gpu_c1 <= 0;
            gpu_c2 <= 0;
            gpu_vx0 <= 0;
            gpu_vy0 <= 0;
            gpu_vz0 <= 0;
            gpu_vx1 <= 0;
            gpu_vy1 <= 0;
            gpu_vz1 <= 0;
            gpu_vx2 <= 0;
            gpu_vy2 <= 0;
            gpu_vz2 <= 0;
        end else begin
            demo_start <= 1'b0;
            demo_clear <= 1'b0;
            demo_present <= 1'b0;
            if(button_press) paused <= !paused;
            if(studio_mode) logo_active <= 1'b0;
            if(logo_active && !paused && boot_elapsed < LOGO_TICKS) boot_elapsed <= boot_elapsed + 1'b1;
            if(frame_elapsed < FRAME_TICKS) frame_elapsed <= frame_elapsed + 1'b1;
            case(state)
                CLEAR_ISSUE:begin
                    demo_clear <= 1'b1;
                    saw_busy <= 1'b0;
                    frame_elapsed <= 1;
                    state <= CLEAR_WAIT;
                end
                CLEAR_WAIT:begin
                    if(gpu_busy) saw_busy <= 1'b1;
                    if(saw_busy && !gpu_busy) state <= INDEX;
                end
                INDEX:begin
                    state <= FETCH;
                end
                FETCH:begin
                    state <= ((studio_mode ? studio_count : frame_count) == 0) ? PRESENT : FETCH_B;
                end
                FETCH_B:begin
                    state <= LOAD;
                end
                LOAD:begin
                    if(studio_mode)begin
                        {gpu_x0, gpu_y0, gpu_x1, gpu_y1, gpu_x2, gpu_y2, gpu_c0, gpu_c1, gpu_c2} <= studio_data;
                        gpu_vx0 <= {1'd0, studio_data[83:74], 7'd0};
                        gpu_vy0 <= {1'd0, studio_data[73:64], 7'd0};
                        gpu_vz0 <= 0;
                        gpu_vx1 <= {1'd0, studio_data[63:54], 7'd0};
                        gpu_vy1 <= {1'd0, studio_data[53:44], 7'd0};
                        gpu_vz1 <= 0;
                        gpu_vx2 <= {1'd0, studio_data[43:34], 7'd0};
                        gpu_vy2 <= {1'd0, studio_data[33:24], 7'd0};
                        gpu_vz2 <= 0;
                    end else begin
                        {gpu_vx0,gpu_vy0,gpu_vz0,gpu_c0,gpu_vx1,gpu_vy1,gpu_vz1,gpu_c1,
                         gpu_vx2,gpu_vy2,gpu_vz2,gpu_c2}<=command_data;
`ifndef SYNTHESIS
                        gpu_x0 <= reference_data[59:50] * H_RES / 640;
                        gpu_y0 <= reference_data[49:40] * V_RES / 480;
                        gpu_x1 <= reference_data[39:30] * H_RES / 640;
                        gpu_y1 <= reference_data[29:20] * V_RES / 480;
                        gpu_x2 <= reference_data[19:10] * H_RES / 640;
                        gpu_y2 <= reference_data[9:0] * V_RES / 480;
`endif
                    end
                    state <= ISSUE;
                end
                ISSUE:begin
                    if(!gpu_busy)begin
                        demo_start <= 1'b1;
                        state <= WAIT_GPU;
                    end
                end
                WAIT_GPU:begin
                    if(gpu_done) state <= gpu_error ? HOLD : ADVANCE;
                end
                ADVANCE:begin
                    if(command_address + 1 >= (studio_mode ? studio_count : frame_count)) state <= PRESENT;
                    else begin
                        command_address <= command_address + 1'b1;
                        state <= INDEX;
                    end
                end
                PRESENT:begin
                    demo_present <= 1'b1;
                    state <= SWAP_WAIT;
                end
                SWAP_WAIT:begin
                    if(present_done) state <= HOLD;
                end
                HOLD:begin
                    if(!studio_mode && !gpu_error && !paused && !button_press)begin
                        if(frame_elapsed >= FRAME_TICKS - 1)begin
                            if(logo_active)begin
                                if(boot_elapsed >= LOGO_TICKS && logo_frame == LOGO_FRAME_COUNT - 1)begin
                                    logo_active <= 1'b0;
                                    animation_frame <= INTRO_NEXT_FRAME;
                                end else if(logo_frame < LOGO_FRAME_COUNT - 1) logo_frame <= logo_frame + 1'b1;
                            end else
                                animation_frame <= (animation_frame == FRAME_COUNT - 1) ? 0 : animation_frame + 1'b1;
                            command_address <= 0;
                            state <= CLEAR_ISSUE;
                        end
                    end
                end
                default:begin
                    state <= CLEAR_ISSUE;
                end
            endcase
        end
    end
    mgpu
    #(
        .H_RES (H_RES),
        .V_RES (V_RES)
    )
    u_mgpu(
        .clk           (gpu_clk                                                 ),
        .rst           (rst                                                     ),
        .start         (demo_start                                              ),
        .clear         (demo_clear                                              ),
        .present       (demo_present                                            ),
        .present_done  (present_done                                            ),
        .vertex_x0     (gpu_vx0                                                 ),
        .vertex_y0     (gpu_vy0                                                 ),
        .vertex_z0     (gpu_vz0                                                 ),
        .vertex_color0 (gpu_c0                                                  ),
        .vertex_x1     (gpu_vx1                                                 ),
        .vertex_y1     (gpu_vy1                                                 ),
        .vertex_z1     (gpu_vz1                                                 ),
        .vertex_color1 (gpu_c1                                                  ),
        .vertex_x2     (gpu_vx2                                                 ),
        .vertex_y2     (gpu_vy2                                                 ),
        .vertex_z2     (gpu_vz2                                                 ),
        .vertex_color2 (gpu_c2                                                  ),
        .m00           (studio_mode ? 18'sd6144 : $signed(matrix_data[287:270]) ),
        .m01           (studio_mode ? 18'sd0 : $signed(matrix_data[269:252])    ),
        .m02           (studio_mode ? 18'sd0 : $signed(matrix_data[251:234])    ),
        .m03           (studio_mode ? 18'sd0 : $signed(matrix_data[233:216])    ),
        .m10           (studio_mode ? 18'sd0 : $signed(matrix_data[215:198])    ),
        .m11           (studio_mode ? -18'sd8192 : $signed(matrix_data[197:180])),
        .m12           (studio_mode ? 18'sd0 : $signed(matrix_data[179:162])    ),
        .m13           (studio_mode ? 18'sd0 : $signed(matrix_data[161:144])    ),
        .m20           (studio_mode ? 18'sd0 : $signed(matrix_data[143:126])    ),
        .m21           (studio_mode ? 18'sd0 : $signed(matrix_data[125:108])    ),
        .m22           (studio_mode ? 18'sd4096 : $signed(matrix_data[107:90])  ),
        .m23           (studio_mode ? 18'sd0 : $signed(matrix_data[89:72])      ),
        .m30           (studio_mode ? -18'sd61344 : $signed(matrix_data[71:54]) ),
        .m31           (studio_mode ? 18'sd61312 : $signed(matrix_data[53:36])  ),
        .m32           (studio_mode ? 18'sd0 : $signed(matrix_data[35:18])      ),
        .m33           (studio_mode ? 18'sd61440 : $signed(matrix_data[17:0])   ),
        .clear_color   (8'h00                                                   ),
        .gpu_busy      (gpu_busy                                                ),
        .gpu_done      (gpu_done                                                ),
        .gpu_error     (gpu_error                                               ),
        .vga_clk       (CLK100MHZ                                               ),
        .vga_rst       (vga_rst                                                 ),
        .vga_r         (VGA_R                                                   ),
        .vga_g         (VGA_G                                                   ),
        .vga_b         (VGA_B                                                   ),
        .vga_hs        (VGA_HS                                                  ),
        .vga_vs        (VGA_VS                                                  )
    );
    initial begin
        $readmemh("scene_commands.mem", commands);
        $readmemh("scene_command_group.mem", command_group);
        $readmemh("scene_matrices.mem", matrices);
        $readmemh("scene_matrix_indices.mem", matrix_indices);
        $readmemh("scene_frame_counts.mem", frame_counts);
        $readmemh("scene_frame_offsets.mem", frame_offsets);
        $readmemh("scene_draw_order.mem", draw_order);
    end
`ifndef SYNTHESIS
    initial begin
        $readmemh("scene_reference_pixels.mem", reference_pixels);
    end
`endif
endmodule
