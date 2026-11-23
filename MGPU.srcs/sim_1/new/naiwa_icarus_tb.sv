`timescale 1ns / 1ps

module naiwa_icarus_tb;

    parameter int TRIANGLE_COUNT = 1;
    parameter real GPU_HALF_PERIOD = 5.0;
    logic clk = 1'b0;
    logic vga_clk = 1'b0;
    logic rst = 1'b1;
    logic vga_rst = 1'b1;
    logic start = 1'b0;
    logic clear = 1'b0;
    logic present = 1'b0;
    logic [7:0] clear_color = 8'h7e;
    logic [16:0] read_addr = 17'd0;
    logic [7:0] read_data;
    logic front_bank;
    logic gpu_busy;
    logic gpu_done;
    logic gpu_error;
    logic present_done;
    logic [31:0] pixel_writes;
    logic [31:0] fragment_writes;
    logic [9:0] pending_pixels;
    logic fifo_empty;
    logic [31:0] matrix_words[0:15];
    logic [31:0] commands[0:TRIANGLE_COUNT*12-1];
    logic [8191:0] matrix_path;
    logic [8191:0] command_path;
    logic [8191:0] output_path;
    logic previous_bank;
    integer triangle;
    integer index;
    integer timeout_count;
    integer fd;
    integer color_value;

    logic signed [17:0] vertex_x0;
    logic signed [17:0] vertex_y0;
    logic signed [17:0] vertex_z0;
    logic [7:0] vertex_color0;
    logic signed [17:0] vertex_x1;
    logic signed [17:0] vertex_y1;
    logic signed [17:0] vertex_z1;
    logic [7:0] vertex_color1;
    logic signed [17:0] vertex_x2;
    logic signed [17:0] vertex_y2;
    logic signed [17:0] vertex_z2;
    logic [7:0] vertex_color2;
    logic signed [17:0] m00;
    logic signed [17:0] m01;
    logic signed [17:0] m02;
    logic signed [17:0] m03;
    logic signed [17:0] m10;
    logic signed [17:0] m11;
    logic signed [17:0] m12;
    logic signed [17:0] m13;
    logic signed [17:0] m20;
    logic signed [17:0] m21;
    logic signed [17:0] m22;
    logic signed [17:0] m23;
    logic signed [17:0] m30;
    logic signed [17:0] m31;
    logic signed [17:0] m32;
    logic signed [17:0] m33;

    always #(GPU_HALF_PERIOD) clk = ~clk;
    always #5 vga_clk = ~vga_clk;

    naiwa_sim u_naiwa_sim (
        .clk             (clk            ),
        .rst             (rst            ),
        .start           (start          ),
        .clear           (clear          ),
        .clear_color     (clear_color    ),
        .present         (present        ),
        .vga_clk         (vga_clk        ),
        .vga_rst         (vga_rst        ),
        .read_addr       (read_addr      ),
        .read_data       (read_data      ),
        .front_bank      (front_bank     ),
        .gpu_busy        (gpu_busy       ),
        .gpu_done        (gpu_done       ),
        .gpu_error       (gpu_error      ),
        .present_done    (present_done   ),
        .pixel_writes    (pixel_writes   ),
        .fragment_writes (fragment_writes),
        .pending_pixels  (pending_pixels ),
        .fifo_empty      (fifo_empty     ),
        .vertex_x0       (vertex_x0      ),
        .vertex_y0       (vertex_y0      ),
        .vertex_z0       (vertex_z0      ),
        .vertex_color0   (vertex_color0  ),
        .vertex_x1       (vertex_x1      ),
        .vertex_y1       (vertex_y1      ),
        .vertex_z1       (vertex_z1      ),
        .vertex_color1   (vertex_color1  ),
        .vertex_x2       (vertex_x2      ),
        .vertex_y2       (vertex_y2      ),
        .vertex_z2       (vertex_z2      ),
        .vertex_color2   (vertex_color2  ),
        .m00             (m00            ),
        .m01             (m01            ),
        .m02             (m02            ),
        .m03             (m03            ),
        .m10             (m10            ),
        .m11             (m11            ),
        .m12             (m12            ),
        .m13             (m13            ),
        .m20             (m20            ),
        .m21             (m21            ),
        .m22             (m22            ),
        .m23             (m23            ),
        .m30             (m30            ),
        .m31             (m31            ),
        .m32             (m32            ),
        .m33             (m33            )
    );

    initial begin
        matrix_path = "matrix.mem";
        command_path = "commands.mem";
        output_path = "icarus.hex";
        if($value$plusargs("MATRIX=%s", matrix_path))begin
        end
        if($value$plusargs("COMMANDS=%s", command_path))begin
        end
        if($value$plusargs("OUTPUT=%s", output_path))begin
        end
        if($value$plusargs("CLEAR=%h", color_value))begin
            clear_color = color_value[7:0];
        end
        $readmemh(matrix_path, matrix_words);
        $readmemh(command_path, commands);
        m00 = matrix_words[0][17:0];
        m01 = matrix_words[1][17:0];
        m02 = matrix_words[2][17:0];
        m03 = matrix_words[3][17:0];
        m10 = matrix_words[4][17:0];
        m11 = matrix_words[5][17:0];
        m12 = matrix_words[6][17:0];
        m13 = matrix_words[7][17:0];
        m20 = matrix_words[8][17:0];
        m21 = matrix_words[9][17:0];
        m22 = matrix_words[10][17:0];
        m23 = matrix_words[11][17:0];
        m30 = matrix_words[12][17:0];
        m31 = matrix_words[13][17:0];
        m32 = matrix_words[14][17:0];
        m33 = matrix_words[15][17:0];
        repeat(10) @(negedge clk);
        rst = 1'b0;
        vga_rst = 1'b0;
        repeat(10) @(negedge clk);
        clear = 1'b1;
        @(negedge clk);
        clear = 1'b0;
        timeout_count = 0;
        while(gpu_busy)begin
            @(negedge clk);
            timeout_count = timeout_count + 1;
            if(timeout_count > 100000) $fatal(1, "Clear timeout");
        end
        for(triangle = 0; triangle < TRIANGLE_COUNT; triangle = triangle + 1)begin
            vertex_x0 = commands[triangle*12+0][17:0];
            vertex_y0 = commands[triangle*12+1][17:0];
            vertex_z0 = commands[triangle*12+2][17:0];
            vertex_color0 = commands[triangle*12+3][7:0];
            vertex_x1 = commands[triangle*12+4][17:0];
            vertex_y1 = commands[triangle*12+5][17:0];
            vertex_z1 = commands[triangle*12+6][17:0];
            vertex_color1 = commands[triangle*12+7][7:0];
            vertex_x2 = commands[triangle*12+8][17:0];
            vertex_y2 = commands[triangle*12+9][17:0];
            vertex_z2 = commands[triangle*12+10][17:0];
            vertex_color2 = commands[triangle*12+11][7:0];
            if(gpu_busy) $fatal(1, "Start while busy");
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            timeout_count = 0;
            while(!gpu_done)begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
                if(timeout_count > 1000000) $fatal(1, "Triangle timeout");
            end
            if(gpu_error) $fatal(1, "GPU rejected triangle %0d", triangle);
            if(pending_pixels != 0 || !fifo_empty || pixel_writes != fragment_writes)
                $fatal(1, "Completion before fragment writeback");
            @(negedge clk);
        end
        previous_bank = front_bank;
        present = 1'b1;
        @(negedge clk);
        present = 1'b0;
        timeout_count = 0;
        while(!present_done)begin
            @(negedge clk);
            timeout_count = timeout_count + 1;
            if(timeout_count > 2000000) $fatal(1, "Present timeout");
        end
        if(front_bank == previous_bank) $fatal(1, "Front buffer did not swap");
        fd = $fopen(output_path, "w");
        if(!fd) $fatal(1, "Cannot open output framebuffer");
        for(index = 0; index < 76800; index = index + 1)begin
            read_addr = index[16:0];
            #1;
            $fwrite(fd, "%02x\n", read_data);
        end
        $fclose(fd);
        $display("PASS NAIWA ICARUS: triangles=%0d pixels=%0d fragments=%0d", TRIANGLE_COUNT, pixel_writes,
                 fragment_writes);
        $finish;
    end

    initial begin
        #2000000000;
        $fatal(1, "Icarus scene timeout");
    end

endmodule
