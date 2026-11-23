module milkfrog_top #(
    parameter int BUTTON_FILTER_BITS = 16,
    parameter int GPU_CLK_DIV_LOG2 = 0,
    parameter int TARGET_FPS = 30,
    parameter int START_FRAME = 0
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

    typedef enum logic [4:0]{
        TIMELINE_FETCH,
        TIMELINE_LOAD,
        ORDER_META_FETCH,
        ORDER_META_LOAD,
        CLEAR_ISSUE,
        CLEAR_WAIT,
        ORDER_FETCH,
        ORDER_LOAD,
        TRIANGLE_FETCH,
        TRIANGLE_LOAD,
        VERTEX0_FETCH,
        VERTEX0_LOAD,
        VERTEX1_FETCH,
        VERTEX1_LOAD,
        VERTEX2_FETCH,
        VERTEX2_LOAD,
        MATRIX0_FETCH,
        MATRIX0_LOAD,
        MATRIX1_FETCH,
        MATRIX1_LOAD,
        INTERPOLATE,
        ISSUE,
        WAIT_GPU,
        ADVANCE,
        PRESENT,
        SWAP_WAIT,
        HOLD,
        ERROR
    } state_t;
    state_t state;

    `include "milkfrog_config.svh"

    localparam int VERTEX_ADDR_W = (VERTEX_COUNT <= 1) ? 1 : $clog2(VERTEX_COUNT);
    localparam int TRI_ADDR_W = (TRIANGLE_COUNT <= 1) ? 1 : $clog2(TRIANGLE_COUNT);
    localparam int GROUP_W = (GROUP_COUNT <= 1) ? 1 : $clog2(GROUP_COUNT);
    localparam int KEY_W = (KEY_COUNT <= 1) ? 1 : $clog2(KEY_COUNT);
    localparam int ORDER_W = (ORDER_LIST_COUNT <= 1) ? 1 : $clog2(ORDER_LIST_COUNT);
    localparam int ORDER_ADDR_W = (ORDER_ENTRY_COUNT <= 1) ? 1 : $clog2(ORDER_ENTRY_COUNT);
    localparam int TRI_COUNT_W = (TRIANGLE_COUNT < 1) ? 1 : $clog2(TRIANGLE_COUNT + 1);
    localparam int FRAME_W = (FRAME_COUNT <= 1) ? 1 : $clog2(FRAME_COUNT);
    localparam int TRIANGLE_W = 3 * VERTEX_ADDR_W + GROUP_W;
    localparam int TIMELINE_W = 2 * KEY_W + 8 + ORDER_W;
    localparam int GPU_HZ = (GPU_CLK_DIV_LOG2 == 0) ? 40000000 : 100000000 / (1 << GPU_CLK_DIV_LOG2);
    localparam int VGA_FRAME_GPU_TICKS = (64'd1667200 * GPU_HZ + 99999999) / 100000000;
    localparam int RAW_FRAME_VBLANKS = (TARGET_FPS > 0) ?
        (100000000 + (TARGET_FPS * 1667200) / 2) / (TARGET_FPS * 1667200) : 1;
    localparam int FRAME_VBLANKS = (RAW_FRAME_VBLANKS < 1) ? 1 : RAW_FRAME_VBLANKS;
    localparam int PRESENT_WAIT_TICKS = (TARGET_FPS > 0) ? (FRAME_VBLANKS - 1) * VGA_FRAME_GPU_TICKS + 8 : 0;

    logic gpu_clk;
    logic gpu_clk_locked;
    logic gpu_reset_request;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic [3:0] reset_pipe = 4'b1111;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic [3:0] gpu_reset_pipe = 4'b1111;
    logic vga_rst = 1'b1;
    logic rst = 1'b1;
    (* ASYNC_REG = "TRUE" *) logic [1:0] button_sync;
    logic [BUTTON_FILTER_BITS-1:0] button_count;
    logic button_level;
    logic button_press;
    logic paused;
    logic [31:0] frame_elapsed;
    logic [FRAME_W-1:0] animation_frame;
    logic [FRAME_W-1:0] completed_frame;
    logic frame_complete;
    logic frame_holding;
    logic frame_drawn;
    logic error_latched;
    logic [TRI_COUNT_W-1:0] draw_index;
    logic [ORDER_ADDR_W-1:0] order_offset;
    logic [TRI_COUNT_W-1:0] frame_triangle_count;
    logic [TRI_ADDR_W-1:0] triangle_address;
    logic [VERTEX_ADDR_W-1:0] vertex_address;
    logic [VERTEX_ADDR_W-1:0] vertex_index1;
    logic [VERTEX_ADDR_W-1:0] vertex_index2;
    logic [GROUP_W-1:0] triangle_group;
    logic [KEY_W-1:0] key0;
    logic [KEY_W-1:0] key1;
    logic [7:0] matrix_alpha;
    logic [ORDER_W-1:0] order_list;
    logic [287:0] matrix_first;
    logic [287:0] matrix_second;
    logic [287:0] matrix_data;
    logic demo_start;
    logic demo_clear;
    logic demo_present;
    logic saw_busy;
    logic gpu_busy;
    logic gpu_done;
    logic gpu_error;
    logic present_done;
    logic signed [17:0] gpu_vx0;
    logic signed [17:0] gpu_vy0;
    logic signed [17:0] gpu_vz0;
    logic [7:0] gpu_c0;
    logic signed [17:0] gpu_vx1;
    logic signed [17:0] gpu_vy1;
    logic signed [17:0] gpu_vz1;
    logic [7:0] gpu_c1;
    logic signed [17:0] gpu_vx2;
    logic signed [17:0] gpu_vy2;
    logic signed [17:0] gpu_vz2;
    logic [7:0] gpu_c2;

    (* rom_style = "block" *) logic [61:0] vertices[0:VERTEX_COUNT-1];
    (* rom_style = "block" *) logic [TRIANGLE_W-1:0] triangles[0:TRIANGLE_COUNT-1];
    (* rom_style = "block" *) logic [TRI_ADDR_W-1:0] draw_order[0:ORDER_ENTRY_COUNT-1];
    (* rom_style = "block" *) logic [287:0] matrices[0:KEY_COUNT*GROUP_COUNT-1];
    (* rom_style = "block" *) logic [TIMELINE_W-1:0] timeline[0:FRAME_COUNT-1];
    (* rom_style = "distributed" *) logic [ORDER_ADDR_W+TRI_COUNT_W-1:0] order_metadata[0:ORDER_LIST_COUNT-1];
    logic [ORDER_ADDR_W+TRI_COUNT_W-1:0] order_meta_raw;
    logic [61:0] vertex_raw;
    logic [TRIANGLE_W-1:0] triangle_raw;
    logic [TRI_ADDR_W-1:0] order_raw;
    logic [287:0] matrix_raw;
    logic [TIMELINE_W-1:0] timeline_raw;

    assign frame_holding = state == HOLD;
    assign frame_drawn = state == PRESENT;

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

    function automatic [287:0] interpolate_matrix;
        input logic [287:0] first;
        input logic [287:0] second;
        input logic [7:0] alpha;
        logic signed [18:0] a;
        logic signed [18:0] b;
        logic signed [18:0] difference;
        logic signed [27:0] product;
        logic signed [28:0] value;
        integer i;
        begin
            for(i = 0; i < 16; i = i + 1)begin
                a = $signed(first[i*18+:18]);
                b = $signed(second[i*18+:18]);
                difference = b - a;
                product = difference * $signed({1'b0, alpha});
                value = a + (product >>> 8);
                interpolate_matrix[i*18+:18] = value[17:0];
            end
        end
    endfunction

    always_ff@(posedge gpu_clk)begin
        if(state == TIMELINE_FETCH) timeline_raw <= timeline[animation_frame];
        if(state == ORDER_META_FETCH) order_meta_raw <= order_metadata[order_list];
        if(state == ORDER_FETCH) order_raw <= draw_order[order_offset+draw_index];
        if(state == TRIANGLE_FETCH) triangle_raw <= triangles[triangle_address];
        if(state == VERTEX0_FETCH || state == VERTEX1_FETCH || state == VERTEX2_FETCH)
            vertex_raw <= vertices[vertex_address];
        if(state == MATRIX0_FETCH) matrix_raw <= matrices[key0*GROUP_COUNT+triangle_group];
        else if(state == MATRIX1_FETCH) matrix_raw <= matrices[key1*GROUP_COUNT+triangle_group];
    end

    always_ff@(posedge gpu_clk)begin
        if(rst)begin
            state <= TIMELINE_FETCH;
            animation_frame <= START_FRAME;
            completed_frame <= START_FRAME;
            frame_complete <= 1'b0;
            error_latched <= 1'b0;
            paused <= 1'b0;
            frame_elapsed <= PRESENT_WAIT_TICKS;
            draw_index <= 0;
            order_offset <= 0;
            frame_triangle_count <= 0;
            triangle_address <= 0;
            vertex_address <= 0;
            vertex_index1 <= 0;
            vertex_index2 <= 0;
            triangle_group <= 0;
            key0 <= 0;
            key1 <= 0;
            matrix_alpha <= 0;
            order_list <= 0;
            matrix_first <= 0;
            matrix_second <= 0;
            matrix_data <= 0;
            demo_start <= 1'b0;
            demo_clear <= 1'b0;
            demo_present <= 1'b0;
            saw_busy <= 1'b0;
            gpu_vx0 <= 0;
            gpu_vy0 <= 0;
            gpu_vz0 <= 0;
            gpu_c0 <= 0;
            gpu_vx1 <= 0;
            gpu_vy1 <= 0;
            gpu_vz1 <= 0;
            gpu_c1 <= 0;
            gpu_vx2 <= 0;
            gpu_vy2 <= 0;
            gpu_vz2 <= 0;
            gpu_c2 <= 0;
        end else begin
            demo_start <= 1'b0;
            demo_clear <= 1'b0;
            demo_present <= 1'b0;
            frame_complete <= 1'b0;
            if(button_press) paused <= !paused;
            if(frame_elapsed < PRESENT_WAIT_TICKS) frame_elapsed <= frame_elapsed + 1'b1;
            case(state)
                TIMELINE_FETCH:begin
                    state <= TIMELINE_LOAD;
                end
                TIMELINE_LOAD:begin
                    {key0, key1, matrix_alpha, order_list} <= timeline_raw;
                    state <= ORDER_META_FETCH;
                end
                ORDER_META_FETCH:begin
                    state <= ORDER_META_LOAD;
                end
                ORDER_META_LOAD:begin
                    {order_offset, frame_triangle_count} <= order_meta_raw;
                    state <= CLEAR_ISSUE;
                end
                CLEAR_ISSUE:begin
                    demo_clear <= 1'b1;
                    saw_busy <= 1'b0;
                    draw_index <= 0;
                    state <= CLEAR_WAIT;
                end
                CLEAR_WAIT:begin
                    if(gpu_busy) saw_busy <= 1'b1;
                    if(saw_busy && !gpu_busy) state <= (frame_triangle_count == 0) ? PRESENT : ORDER_FETCH;
                end
                ORDER_FETCH:begin
                    state <= ORDER_LOAD;
                end
                ORDER_LOAD:begin
                    triangle_address <= order_raw;
                    state <= TRIANGLE_FETCH;
                end
                TRIANGLE_FETCH:begin
                    state <= TRIANGLE_LOAD;
                end
                TRIANGLE_LOAD:begin
                    {vertex_address, vertex_index1, vertex_index2, triangle_group} <= triangle_raw;
                    state <= VERTEX0_FETCH;
                end
                VERTEX0_FETCH:begin
                    state <= VERTEX0_LOAD;
                end
                VERTEX0_LOAD:begin
                    {gpu_vx0, gpu_vy0, gpu_vz0, gpu_c0} <= vertex_raw;
                    vertex_address <= vertex_index1;
                    state <= VERTEX1_FETCH;
                end
                VERTEX1_FETCH:begin
                    state <= VERTEX1_LOAD;
                end
                VERTEX1_LOAD:begin
                    {gpu_vx1, gpu_vy1, gpu_vz1, gpu_c1} <= vertex_raw;
                    vertex_address <= vertex_index2;
                    state <= VERTEX2_FETCH;
                end
                VERTEX2_FETCH:begin
                    state <= VERTEX2_LOAD;
                end
                VERTEX2_LOAD:begin
                    {gpu_vx2, gpu_vy2, gpu_vz2, gpu_c2} <= vertex_raw;
                    state <= MATRIX0_FETCH;
                end
                MATRIX0_FETCH:begin
                    state <= MATRIX0_LOAD;
                end
                MATRIX0_LOAD:begin
                    matrix_first <= matrix_raw;
                    state <= MATRIX1_FETCH;
                end
                MATRIX1_FETCH:begin
                    state <= MATRIX1_LOAD;
                end
                MATRIX1_LOAD:begin
                    matrix_second <= matrix_raw;
                    state <= INTERPOLATE;
                end
                INTERPOLATE:begin
                    matrix_data <= interpolate_matrix(matrix_first, matrix_second, matrix_alpha);
                    state <= ISSUE;
                end
                ISSUE:begin
                    if(!gpu_busy)begin
                        demo_start <= 1'b1;
                        state <= WAIT_GPU;
                    end
                end
                WAIT_GPU:begin
                    if(gpu_done)begin
                        if(gpu_error)begin
                            error_latched <= 1'b1;
                            state <= ERROR;
                        end else begin
                            state <= ADVANCE;
                        end
                    end
                end
                ADVANCE:begin
                    if(draw_index + 1 >= frame_triangle_count)begin
                        state <= PRESENT;
                    end else begin
                        draw_index <= draw_index + 1'b1;
                        state <= ORDER_FETCH;
                    end
                end
                PRESENT:begin
                    if(frame_elapsed >= PRESENT_WAIT_TICKS)begin
                        demo_present <= 1'b1;
                        state <= SWAP_WAIT;
                    end
                end
                SWAP_WAIT:begin
                    if(present_done)begin
                        frame_complete <= 1'b1;
                        frame_elapsed <= 0;
                        completed_frame <= animation_frame;
                        state <= HOLD;
                    end
                end
                HOLD:begin
                    if(!paused && !button_press)begin
                        animation_frame <= (animation_frame == FRAME_COUNT - 1) ? 0 : animation_frame + 1'b1;
                        state <= TIMELINE_FETCH;
                    end
                end
                ERROR:begin
                    error_latched <= 1'b1;
                end
                default:begin
                    state <= TIMELINE_FETCH;
                end
            endcase
        end
    end

    mgpu

    #(
        .H_RES (320),
        .V_RES (240)
    )
    u_mgpu(
        .clk           (gpu_clk                      ),
        .rst           (rst                          ),
        .start         (demo_start                   ),
        .clear         (demo_clear                   ),
        .present       (demo_present                 ),
        .present_done  (present_done                 ),
        .vertex_x0     (gpu_vx0                      ),
        .vertex_y0     (gpu_vy0                      ),
        .vertex_z0     (gpu_vz0                      ),
        .vertex_color0 (gpu_c0                       ),
        .vertex_x1     (gpu_vx1                      ),
        .vertex_y1     (gpu_vy1                      ),
        .vertex_z1     (gpu_vz1                      ),
        .vertex_color1 (gpu_c1                       ),
        .vertex_x2     (gpu_vx2                      ),
        .vertex_y2     (gpu_vy2                      ),
        .vertex_z2     (gpu_vz2                      ),
        .vertex_color2 (gpu_c2                       ),
        .m00           ($signed(matrix_data[0+:18])  ),
        .m01           ($signed(matrix_data[18+:18]) ),
        .m02           ($signed(matrix_data[36+:18]) ),
        .m03           ($signed(matrix_data[54+:18]) ),
        .m10           ($signed(matrix_data[72+:18]) ),
        .m11           ($signed(matrix_data[90+:18]) ),
        .m12           ($signed(matrix_data[108+:18])),
        .m13           ($signed(matrix_data[126+:18])),
        .m20           ($signed(matrix_data[144+:18])),
        .m21           ($signed(matrix_data[162+:18])),
        .m22           ($signed(matrix_data[180+:18])),
        .m23           ($signed(matrix_data[198+:18])),
        .m30           ($signed(matrix_data[216+:18])),
        .m31           ($signed(matrix_data[234+:18])),
        .m32           ($signed(matrix_data[252+:18])),
        .m33           ($signed(matrix_data[270+:18])),
        .clear_color   (CLEAR_COLOR                  ),
        .gpu_busy      (gpu_busy                     ),
        .gpu_done      (gpu_done                     ),
        .gpu_error     (gpu_error                    ),
        .vga_clk       (CLK100MHZ                    ),
        .vga_rst       (vga_rst                      ),
        .vga_r         (VGA_R                        ),
        .vga_g         (VGA_G                        ),
        .vga_b         (VGA_B                        ),
        .vga_hs        (VGA_HS                       ),
        .vga_vs        (VGA_VS                       )
    );

    initial begin
        $readmemh("milkfrog_vertex.mem", vertices);
        $readmemh("milkfrog_triangle.mem", triangles);
        $readmemh("milkfrog_order.mem", draw_order);
        $readmemh("milkfrog_order_meta.mem", order_metadata);
        $readmemh("milkfrog_matrix.mem", matrices);
        $readmemh("milkfrog_timeline.mem", timeline);
    end

`ifndef SYNTHESIS
    initial begin
        if(VERTEX_COUNT < 1 || TRIANGLE_COUNT < 1 || GROUP_COUNT < 1 || KEY_COUNT < 1 || ORDER_LIST_COUNT < 1)
            $fatal(1, "Invalid scene ROM dimensions");
        if(START_FRAME < 0 || START_FRAME >= FRAME_COUNT) $fatal(1, "Invalid starting frame");
    end
    always @(posedge gpu_clk)begin
        if(!rst)begin
            if(state == TIMELINE_LOAD &&
               (timeline_raw[TIMELINE_W-1-:KEY_W] >= KEY_COUNT ||
                timeline_raw[ORDER_W+8+:KEY_W] >= KEY_COUNT || timeline_raw[ORDER_W-1:0] >= ORDER_LIST_COUNT))
                $fatal(1, "Timeline index out of range");
            if(state == ORDER_META_LOAD &&
               (order_meta_raw[TRI_COUNT_W-1:0] > TRIANGLE_COUNT ||
                (order_meta_raw[TRI_COUNT_W+:ORDER_ADDR_W] + order_meta_raw[TRI_COUNT_W-1:0]) > ORDER_ENTRY_COUNT))
                $fatal(1, "Order list metadata out of range");
            if(state == ORDER_LOAD && order_raw >= TRIANGLE_COUNT) $fatal(1, "Triangle address out of range");
            if(state == TRIANGLE_LOAD &&
               (triangle_raw[GROUP_W-1:0] >= GROUP_COUNT ||
                triangle_raw[GROUP_W+:VERTEX_ADDR_W] >= VERTEX_COUNT ||
                triangle_raw[GROUP_W+VERTEX_ADDR_W+:VERTEX_ADDR_W] >= VERTEX_COUNT ||
                triangle_raw[GROUP_W+2*VERTEX_ADDR_W+:VERTEX_ADDR_W] >= VERTEX_COUNT))
                $fatal(1, "Vertex or group address out of range");
            if(gpu_done && (u_mgpu.pending_pixels != 0 || !u_mgpu.fifo_rs_empty))
                $fatal(1, "Triangle completion before writeback drained");
        end
    end
`endif

endmodule
