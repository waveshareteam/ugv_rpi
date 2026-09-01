const fetchGetPhotoNames = '/get_photo_names';
const fetchDeletePhoto = '/delete_photo';
const fetchGetVideoNames = '/get_video_names';
const fetchDeleteVideo = '/delete_video';

function generatePhotoLink(imgname) {
    var strippedname = imgname.replace("photo_", "").replace(".jpg", "");
    var photoLink = '<li><a target="_blank" href="/media/pictures/' + imgname + '" ><img class="photo_img" data-filename="' + imgname + '" src="/media/pictures/' + imgname + '" /></a>';
    photoLink += '<p>' + strippedname + '</p>';
    photoLink += '<div class="delete_btn"><button class="normal_btn delete_btn_size normal_btn_del btn_ico"></button></div></li>';
    return photoLink;
}

export function updatePhotoNames() {
    $.get(fetchGetPhotoNames, function (data) {
        var photoLinks = '';
        if (window.location.pathname === '/') {
            for (var i = 0; i < Math.min(6, data.length); i++) {
                var name = data[i];
                photoLinks += generatePhotoLink(name);
            }
        } else {
            for (var i = 0; i < data.length; i++) {
                var name = data[i];
                photoLinks += generatePhotoLink(name);
            }
        }
        $('#photo-list').html(photoLinks);
        $("#number-photos").text(data.length);
        $("#photo-list li button").on("click", function () {
            var filename = $(this).closest("li").find("img.photo_img").data('filename');
            $.post(fetchDeletePhoto, { filename: filename }, function (response) {
                if (response.success) {
                    updatePhotoNames();
                } else {
                    alert("Failed to delete the file.");
                }
            });
        });
    });
}

function showVideosTips() {
    var videostipsbox = $("#video-del-tips");
    videostipsbox.css("opacity", "1");
    videostipsbox.css("transform", `translate(-50%, -100%)`);
    setTimeout(function () {
        videostipsbox.removeAttr("style");
    }, 2000);
}

function generateVideoLink(vname) {
    var strippedname = vname.replace("video_", "").replace(".mp4", "");
    var videoList = '<li><a target="_blank" data-filename="' + vname + '" href="/media/videos/' + vname + '">';
    videoList += '<p>' + strippedname + '</p>';
    videoList += '<div><div class="delete_btn_size normal_btn_play btn_ico"></div></div></a>';
    videoList += '<div class="delete_btn"><div class="delete_btn_size normal_btn_del btn_ico"></div></div></li>';
    return videoList;
}

export function updateVideoList() {
    $.get(fetchGetVideoNames, function (data) {
        var videosLists = '';
        if (window.location.pathname === '/') {
            for (var i = 0; i < Math.min(6, data.length); i++) {
                var name = data[i];
                videosLists += generateVideoLink(name);
            }
        } else {
            for (var i = 0; i < data.length; i++) {
                var name = data[i];
                videosLists += generateVideoLink(name);
            }
        }
        $('#video-list').html(videosLists);
        $("#number-videos").text(data.length);
        $("#video-list li div.normal_btn_del").on("click", function () {
            var filename = $(this).closest("li").find("a").data('filename');
            $.post(fetchDeleteVideo, { filename: filename }, function (response) {
                if (response.success) {
                    updateVideoList();
                    showVideosTips();
                } else {
                    alert("Failed to delete the video.");
                }
            });
        });
    });
}

updatePhotoNames();
updateVideoList();
