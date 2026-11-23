#include "Vnaiwa_sim.h"
#include "verilated.h"
#include <array>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sstream>

namespace fs = std::filesystem;

double sc_time_stamp() { return 0; }

uint32_t read_word(std::ifstream& in) {
    uint32_t value = 0;
    in.read(reinterpret_cast<char*>(&value), sizeof(value));
    if (!in) throw std::runtime_error("Truncated command file");
    return value;
}

int main(int argc, char** argv) {
    try {
        if (argc < 3) throw std::runtime_error("Usage: naiwa_sim scene.bin output_directory [clear_color_hex]");
        VerilatedContext context;
        context.commandArgs(argc, argv);
        Vnaiwa_sim dut(&context);
        const auto clear_color = argc > 3 ? std::stoul(argv[3], nullptr, 16) : 0x7e;
        if (clear_color > 255) throw std::runtime_error("Clear color must fit RGB332");
        dut.clear_color = clear_color;
        std::ifstream in(argv[1], std::ios::binary);
        if (!in || read_word(in) != 0x4e414957) throw std::runtime_error("Invalid scene header");
        const auto frames = read_word(in), width = read_word(in), height = read_word(in);
        if (width != 320 || height != 240) throw std::runtime_error("Unexpected framebuffer dimensions");
        fs::path output(argv[2]); fs::create_directories(output);
        std::ofstream report(output / "frames.csv");
        report << "frame,triangles,draw_cycles,present_cycles,pixel_writes,front_bank\n";
        std::array<uint32_t, 16> matrix;
        for (auto& word : matrix) word = read_word(in) & 0x3ffff;
        dut.m00=matrix[0]; dut.m01=matrix[1]; dut.m02=matrix[2]; dut.m03=matrix[3];
        dut.m10=matrix[4]; dut.m11=matrix[5]; dut.m12=matrix[6]; dut.m13=matrix[7];
        dut.m20=matrix[8]; dut.m21=matrix[9]; dut.m22=matrix[10]; dut.m23=matrix[11];
        dut.m30=matrix[12]; dut.m31=matrix[13]; dut.m32=matrix[14]; dut.m33=matrix[15];
        uint64_t cycles = 0;
        auto tick = [&]() {
            dut.clk=0; dut.vga_clk=0; dut.eval(); context.timeInc(5);
            dut.clk=1; dut.vga_clk=1; dut.eval(); context.timeInc(5); ++cycles;
            if (context.gotFinish()) throw std::runtime_error("Unexpected RTL finish");
        };
        dut.rst=1; dut.vga_rst=1; dut.start=0; dut.clear=0; dut.present=0; dut.read_addr=0;
        for (int j=0;j<10;++j) tick();
        dut.rst=0; dut.vga_rst=0;
        for (int j=0;j<10;++j) tick();
        const auto wall_start = std::chrono::steady_clock::now();
        for (uint32_t f=0; f<frames; ++f) {
            const auto index=read_word(in), triangles=read_word(in);
            const auto begin=cycles;
            const auto writes_before=dut.pixel_writes;
            const auto fragments_before=dut.fragment_writes;
            dut.clear=1; tick(); dut.clear=0;
            uint64_t limit=cycles+100000;
            do { tick(); if (cycles>limit) throw std::runtime_error("Clear timeout"); } while(dut.gpu_busy);
            for(uint32_t t=0;t<triangles;++t) {
                std::array<uint32_t,12> v;
                for (auto& word:v) word=read_word(in);
                dut.vertex_x0=v[0]&0x3ffff; dut.vertex_y0=v[1]&0x3ffff; dut.vertex_z0=v[2]&0x3ffff; dut.vertex_color0=v[3];
                dut.vertex_x1=v[4]&0x3ffff; dut.vertex_y1=v[5]&0x3ffff; dut.vertex_z1=v[6]&0x3ffff; dut.vertex_color1=v[7];
                dut.vertex_x2=v[8]&0x3ffff; dut.vertex_y2=v[9]&0x3ffff; dut.vertex_z2=v[10]&0x3ffff; dut.vertex_color2=v[11];
                if (dut.gpu_busy) throw std::runtime_error("Start while busy");
                dut.start=1; tick(); dut.start=0;
                limit=cycles+1000000;
                do { tick(); if (cycles>limit) throw std::runtime_error("Triangle timeout"); } while(!dut.gpu_done);
                if (dut.gpu_error) throw std::runtime_error("GPU rejected triangle " + std::to_string(t));
                if (dut.pending_pixels || !dut.fifo_empty || dut.pixel_writes != dut.fragment_writes)
                    throw std::runtime_error("Triangle completed before all fragments reached the framebuffer");
                tick();
            }
            const auto drawn=cycles;
            const auto old_bank=dut.front_bank;
            dut.present=1; tick(); dut.present=0;
            limit=cycles+2000000;
            do { tick(); if(cycles>limit) throw std::runtime_error("Present timeout"); } while(!dut.present_done);
            if(dut.front_bank==old_bank) throw std::runtime_error("Front buffer did not swap");
            const auto presented=cycles;
            std::ostringstream filename;
            filename << "frame_" << std::setw(4) << std::setfill('0') << index << ".rgb332";
            const std::string name = filename.str();
            std::ofstream pixels(output / name, std::ios::binary);
            for(uint32_t address=0;address<width*height;++address) {
                dut.read_addr=address; dut.eval();
                const unsigned char pixel=dut.read_data;
                pixels.write(reinterpret_cast<const char*>(&pixel),1);
            }
            if(!pixels) throw std::runtime_error("Framebuffer write failed");
            if (dut.pixel_writes-writes_before != dut.fragment_writes-fragments_before)
                throw std::runtime_error("Frame fragment/writeback count mismatch");
            report << index << ',' << triangles << ',' << drawn-begin << ',' << presented-drawn << ',' << dut.pixel_writes-writes_before << ',' << unsigned(dut.front_bank) << '\n';
            report.flush();
            const double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-wall_start).count();
            std::cout << "PASS frame=" << index << " triangles=" << triangles << " gpu_cycles=" << drawn-begin << " wall=" << elapsed << "s" << std::endl;
        }
        if(in.peek()!=std::ifstream::traits_type::eof()) throw std::runtime_error("Unexpected trailing commands");
        dut.final();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << std::endl;
        return 1;
    }
}
