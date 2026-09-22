"""Use the handwritten MGPU clear engine for board scene transitions."""
from pathlib import Path


def integrate_clear(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if '// Hardware full-screen clear handshake' in text:
        return
    text = text.replace('sequence; clearing is performed with triangles through the existing GPU.',
                        'sequence; full-screen clears use the MGPU clear engine.')
    if 'reg demo_clear;' not in text:
        text = text.replace('    reg demo_start;', '    reg demo_start;\n    reg demo_clear;')
    if '.clear(demo_clear)' not in text:
        text = text.replace('.start(demo_start),', '.start(demo_start), .clear(demo_clear),')
    text = text.replace('ADVANCE=4, HOLD=5;', 'ADVANCE=4, HOLD=5, CLEAR_ISSUE=6, CLEAR_WAIT=7;')
    text = text.replace('    always @(posedge gpu_clk) begin\n        if(rst) begin\n            demo_state', '''    // Hardware full-screen clear handshake. Scene ROM addresses stay stable;
    // skip the two old full-screen triangles after the clear has completed.
    wire needs_full_clear =
`ifdef STUDIO_SIMULATION
        !studio_mode &&
`endif
        (logo_active ? (logo_command==0) :
         ((scene==0 && command_address==0) ||
          (scene==1 && command_address==ART_START)));
    always @(posedge gpu_clk) begin
        if(rst) begin
            demo_state''')
    text = text.replace('saw_busy<=0; demo_start<=0;', 'saw_busy<=0; demo_start<=0; demo_clear<=0;')
    text = text.replace('            demo_start<=0;\n            case', '            demo_start<=0; demo_clear<=0;\n            case')
    text = text.replace('demo_state<=LOAD; // synchronous command-source read latency',
                        'demo_state<=needs_full_clear ? CLEAR_ISSUE : LOAD; // synchronous source read')
    text = text.replace('                LOAD: begin', '''                CLEAR_ISSUE: begin
                    // Entered only at startup or after a completed scene hold.
                    demo_clear<=1; saw_busy<=0;
                    demo_state<=CLEAR_WAIT;
                end
                CLEAR_WAIT: begin
                    if(gpu_busy) saw_busy<=1;
                    if(saw_busy && !gpu_busy) begin
                        if(logo_active) logo_command<=14'd2;
                        else command_address<=command_address+13'd2;
                        demo_state<=FETCH;
                    end
                end
                LOAD: begin''')
    assert 'needs_full_clear ? CLEAR_ISSUE' in text
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    integrate_clear(Path(__file__).resolve().parents[1] / 'MGPU.srcs/sources_1/new/top.v')
