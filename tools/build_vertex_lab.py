from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def generate():
    target=ROOT/'MGPU.srcs/sources_1/new/top.sv'
    source=target.read_text(encoding='utf-8')

    import orbit_scene
    from orbit_scene import matrix,project as orbit_project,order,FRAME_COUNT
    import midiyas_logo
    triangles=list(orbit_scene.scene())
    model_count=len(triangles)
    orders=[order(frame) for frame in range(FRAME_COUNT)]
    key_count=FRAME_COUNT//orbit_scene.KEY_STRIDE
    matrices=[orbit_scene.key_matrix(key,group) for key in range(key_count) for group in range(orbit_scene.GROUP_COUNT)]
    logo_triangles=midiyas_logo.scene()
    logo_count=len(logo_triangles)-model_count
    triangles+=logo_triangles[:logo_count]
    groups=[16+group for group in orbit_scene.groups()]+list(midiyas_logo.groups())[:logo_count]
    assert len(groups)==len(triangles) and all(0<=group<midiyas_logo.GROUP_COUNT for group in groups)
    orders+=[[model_count+i if i<logo_count else i-logo_count for i in midiyas_logo.order(frame)] for frame in range(midiyas_logo.FRAME_COUNT)]
    matrices+=[midiyas_logo.matrix(frame,group) for frame in range(midiyas_logo.FRAME_COUNT) for group in range(midiyas_logo.GROUP_COUNT)]
    matrix_indices=[];unique_matrices=[];matrix_lookup={}
    for values in matrices:
        key=tuple(values)
        if key not in matrix_lookup:
            matrix_lookup[key]=len(unique_matrices);unique_matrices.append(values)
        matrix_indices.append(matrix_lookup[key])
    matrices=unique_matrices
    frame_offsets=[];order_count=0;unique_orders=[];order_lookup={}
    for ordering in orders:
        key=tuple(ordering)
        if key not in order_lookup:
            order_lookup[key]=order_count;unique_orders.append((order_count,ordering));order_count+=len(ordering)
        frame_offsets.append(order_lookup[key])
    assert len(triangles)<=2048
    assert FRAME_COUNT%orbit_scene.KEY_STRIDE==0 and orbit_scene.KEY_STRIDE==8
    index_bits=max(1,(len(triangles)-1).bit_length())
    count_bits=max(1,max(map(len,orders)).bit_length())
    group_bits=max(1,(midiyas_logo.GROUP_COUNT-1).bit_length())
    matrix_bits=max(1,(len(matrices)-1).bit_length())
    order_bits=max(1,(order_count-1).bit_length())
    body = ''
    for index,(vertices,pixels,colors) in enumerate(triangles):
        word=0
        for vertex,color in zip(vertices,colors):
            for coordinate in vertex:word=(word<<18)|(coordinate&0x3ffff)
            word=(word<<8)|color
        body+=f"        commands[{index}]=186'h{word:047x};\n"
        body+=f"        command_group[{index}]={group_bits}'d{groups[index]};\n"
    for address,values in enumerate(matrices):
        word=0
        for value in values:word=(word<<18)|(value&0x3ffff)
        body+=f"        matrices[{address}]=288'h{word:072x};\n"
    for address,index in enumerate(matrix_indices):
        body+=f"        matrix_indices[{address}]={matrix_bits}'d{index};\n"
    for frame,ordering in enumerate(orders):
        body+=f"        frame_counts[{frame}]={count_bits}'d{len(ordering)};\n"
        body+=f"        frame_offsets[{frame}]={order_bits}'d{frame_offsets[frame]};\n"
    for offset,ordering in unique_orders:
        for index,ident in enumerate(ordering):
            body+=f"        draw_order[{offset+index}]={index_bits}'d{ident};\n"

    order_stride=1<<count_bits
    for frame,ordering in enumerate(orders):
        for index,ident in enumerate(ordering):
            word=0
            transform=matrix(frame,groups[ident]-16) if frame<FRAME_COUNT else midiyas_logo.matrix(frame-FRAME_COUNT,groups[ident])
            for vertex in triangles[ident][0]:
                for value in orbit_project(vertex,transform)[0]:word=(word<<10)|value
            body+=f"        reference_pixels[{frame*order_stride+index}]=60'h{word:015x};\n"


    from scene_rom import write_rom
    write_rom(body, ROOT/'MGPU.srcs/sources_1/rom')
    values = dict(COMMAND_COUNT=len(triangles), FRAME_COUNT=FRAME_COUNT,
        LOGO_FRAME_COUNT=midiyas_logo.FRAME_COUNT, LOGO_GROUP_COUNT=midiyas_logo.GROUP_COUNT,
        MODEL_GROUP_COUNT=orbit_scene.GROUP_COUNT, MODEL_KEY_COUNT=key_count,
        MATRIX_COUNT=len(matrices), ORDER_COUNT=order_count,
        INTRO_NEXT_FRAME=midiyas_logo.INTRO_NEXT_FRAME, ORDER_STRIDE=order_stride)
    import re
    for name, value in values.items():
        source, count = re.subn(r'(localparam(?: int)? '+name+r'\s*=\s*)\d+',
                                lambda match: match[1]+str(value), source)
        if count != 1:
            raise ValueError(f'Missing or duplicate constant: {name}')
    widths = dict(command_group=group_bits, draw_order=index_bits, order_data=index_bits,
                  frame_counts=count_bits, frame_count=count_bits)
    for name, width in widths.items():
        source = re.sub(r'(logic\s+)\[\d+:0\](\s+'+name+r'\b)',
                        lambda match: match[1]+f'[{width-1}:0]'+match[2], source)
    target.write_text(source, encoding='utf-8', newline='\n')
    output=ROOT/'out/vertex_lab';output.mkdir(parents=True,exist_ok=True)
    (output/'scene.json').write_text(json.dumps(triangles))
    print(f'{len(triangles)} triangles -> {target}')


if __name__=='__main__':generate()
