# Literature review

Two bodies of work bear on this project. One is image captioning, which taught machines to
describe pictures. The other is accessibility research, which asked what blind and low vision
users actually need from a description. They rarely cite each other, and the gap between them
is where this project sits.

## The captioning line

Vinyals, Toshev, Bengio and Erhan, "Show and Tell: A Neural Image Caption Generator", CVPR
2015. https://arxiv.org/abs/1411.4555
The paper that set the template: a convolutional encoder feeding a recurrent decoder, trained
to maximize the likelihood of a reference caption. Everything after it inherits that objective,
which is to match how a human described the picture. It never asks what the picture is doing on
a page.

Li, Li, Xiong and Hoi, "BLIP: Bootstrapping Language-Image Pre-training for Unified
Vision-Language Understanding and Generation", ICML 2022. https://arxiv.org/abs/2201.12086
BLIP unifies understanding and generation in one pretrained model and cleans noisy web
image-text pairs by captioning them and filtering the results. It is the strongest pure
captioner that is small enough to run on a laptop, which is why it serves as the baseline
here. It takes no instruction, so it always answers the same question: what does this look
like.

Li, Li, Savarese and Hoi, "BLIP-2: Bootstrapping Language-Image Pre-training with Frozen Image
Encoders and Large Language Models", ICML 2023. https://arxiv.org/abs/2301.12597
BLIP-2 keeps the vision encoder and the language model frozen and trains a small query
transformer between them. Captioning then inherits whatever the language model can do,
including following an instruction, which is the step that makes prompting conditions possible
at all.

Liu, Li, Wu and Lee, "Visual Instruction Tuning", NeurIPS 2023.
https://arxiv.org/abs/2304.08485
LLaVA tunes a vision-language model on generated instruction-following data. After this we
can tell a model what kind of answer we want rather than only asking it to caption. This is
what makes a WCAG-informed prompt a plausible fix, and testing that fix is the point of the
experiment.

Wang et al., "Qwen2-VL: Enhancing Vision-Language Model's Perception of the World at Any
Resolution", 2024. https://arxiv.org/abs/2409.12191
Qwen2-VL handles native resolutions, reads text in images well, and the 2B variant runs on a
laptop at a few seconds per image. Both reasons matter here: text in image is one of the alt
text categories, and the whole sweep has to fit on one machine.

## The accessibility line

Gurari et al., "VizWiz Grand Challenge: Answering Visual Questions from Blind People", CVPR
2018. https://arxiv.org/abs/1802.08218
The first large vision dataset whose images were taken by blind photographers with a real goal
in mind: blurry, badly framed, and asked about for a reason. Gurari, Zhao, Zhang and
Bhattacharya then released VizWiz-Captions at ECCV 2020, https://arxiv.org/abs/2002.08565,
pairing 39,000 of those images with five captions each. Both cover photographs, not interface
elements, which is the slice this project adds.

Wu, Wieland, Farivar and Schiller, "Automatic Alt-Text: Computer-generated Image Descriptions
for Blind Users on a Social Network Service", CSCW 2017.
https://doi.org/10.1145/2998181.2998364
Facebook shipped generated alt text to screen reader users and reported what happened. The
useful finding is about trust: users wanted to know how confident the system was, and a hedged,
sparse description beat a fluent one that might be wrong. Generated alt text has been in
production for a decade, so its failure modes are current, not hypothetical.

Gleason, Carrington, Cassidy, Morris, Kitani and Bigham, "It's almost like they're trying to
hide it: How User-Provided Image Descriptions Have Failed to Make Twitter Accessible", WWW
2019. https://doi.org/10.1145/3308558.3313605
A measurement of alt text in the wild. Roughly 0.1 percent of images on Twitter carried a
description, and even users who had turned the feature on wrote one about half the time. This
is the argument for automation: the manual path has been available for years and almost nobody
takes it.

Stangl, Morris and Gurari, "Person, Shoes, Tree. Is the Person Naked? What People with Vision
Impairments Want in Image Descriptions", CHI 2020. https://doi.org/10.1145/3313831.3376404
Interviews with 28 blind and low vision participants across news, shopping, social and dating
sites. What people want turns out to depend on where the image sits, so the same picture needs
different descriptions in different places. That is a direct statement that context, not
pixels alone, determines the right answer.

## The metric critique

Papineni, Roukos, Ward and Zhu, "BLEU: a Method for Automatic Evaluation of Machine
Translation", ACL 2002. https://aclanthology.org/P02-1040/
Vedantam, Zitnick and Parikh, "CIDEr: Consensus-based Image Description Evaluation", CVPR
2015. https://arxiv.org/abs/1411.5726
Anderson, Fernando, Johnson and Gould, "SPICE: Semantic Propositional Image Caption
Evaluation", ECCV 2016. https://arxiv.org/abs/1607.08822
These three are how captioning is scored. BLEU counts n-gram overlap, CIDEr weights that
overlap by annotator agreement, and SPICE compares scene graphs of objects, attributes and
relations. All three measure agreement with reference descriptions, and none can tell whether a
button is operable, because that fact is in neither the references nor the image. A model can
score well on all three and still leave a search button silent.

Kreiss, Bennett, Hooshmand, Zelikman, Morris and Potts, "Context Matters for Image
Descriptions for Accessibility: Challenges for Referenceless Evaluation Metrics", EMNLP 2022.
https://arxiv.org/abs/2205.10646
The closest work to this project. Blind and low vision participants rated descriptions, and
the ratings depended on the surrounding context in ways the standard metrics do not capture.
Kreiss and colleagues respond by adapting the metric. This project responds by changing the
input instead: give the model the DOM around the image and see whether functional accuracy
recovers.

## What is missing

No benchmark here is organized by what an image is for. The W3C alt decision tree,
https://www.w3.org/WAI/tutorials/images/decision-tree/, sorts web images into a few categories,
and the right answer is a different kind of thing in each: a verb for a control, nothing for a
decoration, a transcription for an image of text. Captioning datasets are photographs with
reference sentences, so the decorative and functional cases cannot even be expressed in them.
That is the set this project builds, and functional images are where a wrong answer costs the
user most.
