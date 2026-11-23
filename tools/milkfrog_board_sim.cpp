#include "Vmilkfrog_board_sim.h"
#include "verilated.h"
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

double sc_time_stamp() { return 0; }

int main(int argc, char** argv) {
    try {
        if(argc < 3) throw std::runtime_error("Usage: milkfrog_board_sim output_directory frames [controls]");
        const auto requested = std::stoul(argv[2]);
        if(requested < 1) throw std::runtime_error("Frame count must be positive");
        const std::filesystem::path output(argv[1]);
        std::filesystem::create_directories(output);
        std::ofstream report(output / "frames.csv");
        report << "capture,animation_frame,root_cycles,gpu_cycles,draw_cycles,triangles,pixel_writes,front_bank\n";
        VerilatedContext context;
        context.commandArgs(argc, argv);
        Vmilkfrog_board_sim dut(&context);
        uint64_t root_cycles = 0;
        auto tick = [&]() {
            dut.clk=0; dut.eval(); context.timeInc(5);
            dut.clk=1; dut.eval(); context.timeInc(5); ++root_cycles;
            if(context.gotFinish()) throw std::runtime_error("Unexpected RTL finish");
            if(dut.error_latched) throw std::runtime_error("Board top latched GPU error");
        };
        dut.reset_n=0; dut.button=0; dut.read_addr=0;
        for(int j=0;j<40;++j) tick();
        dut.reset_n=1;
        uint32_t last_gpu_cycles=0, last_triangles=0, last_writes=0;
        bool previous_complete=false;
        unsigned last_bank=0;
        auto wall = std::chrono::steady_clock::now();
        for(uint32_t capture=0;capture<requested;++capture) {
            uint64_t limit=root_cycles+30000000;
            while(true) {
                tick();
                const bool current=dut.frame_complete;
                if(current && !previous_complete) { previous_complete=current; break; }
                previous_complete=current;
                if(root_cycles>limit) throw std::runtime_error("Board frame timeout");
            }
            if(dut.front_bank==last_bank) throw std::runtime_error("Board front buffer did not swap");
            if(dut.pending_pixels || !dut.fifo_empty) throw std::runtime_error("Board present before writeback drained");
            last_bank=dut.front_bank;
            std::ostringstream name; name << "frame_" << std::setw(4) << std::setfill('0') << capture << ".rgb332";
            std::ofstream framebuffer(output/name.str(),std::ios::binary);
            for(uint32_t address=0;address<76800;++address) {
                dut.read_addr=address; dut.eval();
                const unsigned char pixel=dut.read_data;
                framebuffer.write(reinterpret_cast<const char*>(&pixel),1);
            }
            if(!framebuffer) throw std::runtime_error("Cannot write board framebuffer");
            report << capture << ',' << dut.completed_frame << ',' << root_cycles << ',' << dut.gpu_cycles-last_gpu_cycles << ',' << dut.draw_cycles << ','
                   << dut.issue_count-last_triangles << ',' << dut.pixel_writes-last_writes << ',' << unsigned(dut.front_bank) << '\n';
            report.flush();
            const double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-wall).count();
            std::cout << "PASS capture=" << capture << " animation_frame=" << dut.completed_frame << " triangles="
                      << dut.issue_count-last_triangles << " wall=" << elapsed << "s" << std::endl;
            last_gpu_cycles=dut.gpu_cycles; last_triangles=dut.issue_count; last_writes=dut.pixel_writes;
        }
        if(argc > 3 && std::string(argv[3]) == "controls") {
            dut.button=1;
            for(unsigned j=0;j<140000;++j) tick();
            if(!dut.paused) throw std::runtime_error("Button did not pause the animation");
            uint64_t limit=root_cycles+30000000;
            while(!dut.holding) { tick(); if(root_cycles>limit) throw std::runtime_error("Pause did not reach frame boundary"); }
            const auto pause_frame=dut.completed_frame;
            const auto pause_bank=dut.front_bank;
            const auto pause_issues=dut.issue_count;
            for(unsigned j=0;j<200000;++j) tick();
            if(!dut.paused || dut.completed_frame!=pause_frame || dut.front_bank!=pause_bank || dut.issue_count!=pause_issues)
                throw std::runtime_error("Paused animation advanced");
            dut.button=0;
            for(unsigned j=0;j<140000;++j) tick();
            if(!dut.paused) throw std::runtime_error("Button release unexpectedly resumed playback");
            dut.button=1;
            for(unsigned j=0;j<140000;++j) tick();
            if(dut.paused) throw std::runtime_error("Second button press did not resume playback");
            limit=root_cycles+30000000;
            while(!dut.frame_complete) { tick(); if(root_cycles>limit) throw std::runtime_error("Resume frame timeout"); }
            if(dut.completed_frame!=(pause_frame+1)%dut.animation_length)
                throw std::runtime_error("Resume skipped the expected animation frame");
            dut.button=0; dut.reset_n=0;
            for(unsigned j=0;j<40;++j) tick();
            dut.reset_n=1;
            limit=root_cycles+30000000;
            while(!dut.frame_complete) { tick(); if(root_cycles>limit) throw std::runtime_error("Reset frame timeout"); }
            if(dut.completed_frame!=0 || dut.paused) throw std::runtime_error("Reset did not restart frame zero");
            std::ifstream first(output/"frame_0000.rgb332",std::ios::binary);
            for(uint32_t address=0;address<76800;++address) {
                dut.read_addr=address; dut.eval();
                const int expected=first.get();
                if(expected<0 || dut.read_data!=expected) throw std::runtime_error("Reset framebuffer differs from initial frame");
            }
            std::ofstream controls(output/"controls.json");
            controls << "{\"pause_at_frame_boundary\":true,\"pause_stable\":true,\"resume_next_frame\":true,\"reset_frame_zero_equal\":true}\n";
            std::cout << "PASS pause, resume and reset framebuffer" << std::endl;
        }
        dut.final();
        return 0;
    } catch(const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << std::endl;
        return 1;
    }
}
