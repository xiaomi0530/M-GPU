`timescale 1ns/1ps
// Focused regression: actual top + MGPU, startup clear and reset during clear.
module top_clear_tb;
    reg clk=0, reset_n=0;
    always #5 clk=~clk;
    wire [3:0] r,g,b;
    wire hs,vs;
    top #(.GPU_CLK_DIV_LOG2(1)) dut(clk,reset_n,1'b0,r,g,b,hs,vs);
    integer writes=0, requests=0;
    reg previous_clear=0;
    always @(posedge dut.gpu_clk) begin
        if(dut.rst) begin
            writes=0;
            previous_clear=0;
        end else begin
            if(dut.demo_clear) begin
                if(previous_clear) $fatal(1,"Clear request longer than one cycle");
                requests=requests+1;
            end
            previous_clear=dut.demo_clear;
            if(dut.u_mgpu.clear_reg) begin
                if(dut.demo_start || dut.u_mgpu.shad_done)
                    $fatal(1,"Clear overlaps draw");
                if(dut.u_mgpu.clear_count!==writes)
                    $fatal(1,"Nonsequential clear address");
                writes=writes+1;
            end
        end
    end
    task reset_board;
        begin
            reset_n=0;
            repeat(30) @(negedge clk);
            if(dut.gpu_busy!==0) $fatal(1,"Busy not reset");
            reset_n=1;
        end
    endtask
    task await_picture;
        begin
            wait(dut.demo_start);
            @(negedge clk);
            if(writes!=307200 || dut.logo_command!=2 || dut.gpu_busy!==0)
                $fatal(1,"Drawing started before full clear or old triangles were not skipped");
        end
    endtask
    initial begin
        reset_board;
        await_picture;
        reset_board;
        wait(writes==100);
        @(negedge clk);
        reset_board;
        await_picture;
        if(requests!=3) $fatal(1,"Unexpected clear request count");
        $display("PASS TOP CLEAR: startup, repeated reset, reset during clear, 307200 addresses");
        $finish;
    end
    initial begin #20000000; $fatal(1,"Clear handshake timeout"); end
endmodule
